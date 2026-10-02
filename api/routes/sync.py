"""
Cihazlar arası senkronizasyon endpoint'leri.

Endpoint'ler:
  POST   /api/sync/push                    → HLC'li kayıtları koşullu uygula
  GET    /api/sync/pull?since=...          → Tam döküm veya delta çek
  GET    /api/sync/devices                 → Bağlı cihaz listesi
  DELETE /api/sync/devices/{device_id}     → Cihazı iptal et

Karar modeli (SYNC_AUTH_PLAN.md §2.2):
    Sunucu tüm otoritelerdir. LWW kararı `(hlc_wall, hlc_counter, device_id)`
    üçlüsüyle BİR KEZ ve merkezî olarak verilir; böylece iki cihaz aynı anda
    push etse bile sonuç deterministiktir.

    Gelen HLC > mevcut HLC → uygula (kazanır)
    Gelen HLC ≤ mevcut HLC → reddet + SUNUCU SÜRÜMÜNÜ DÖNDÜR

Reddetme yanıtı sessiz veri kaybını önler: kaybeden cihaz sunucu sürümüyle
uzlaşır, kullanıcı hiçbir şey kaybetmez.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Query, status

from api.deps import HTTP_413_TOO_LARGE, CurrentUser, get_supabase_async
from Core.Helpers.Cli import debug_log, konsol
from Core.Libs.Supabase import (
    PushTooLargeError,
    SupabaseConfigurationError,
    SupabaseManager,
)
from Core.Libs.SyncModels import (
    DOCUMENT_TYPES,
    MAX_DOCUMENTS_PER_PUSH,
    MAX_PAYLOAD_BYTES,
    MAX_RECORDS_PER_PUSH,
    PULL_PAGE_SIZE,
    SUPPORTED_SCHEMA_VERSION,
    DeviceSummary,
    DocumentIn,
    PullDocument,
    PullRecord,
    PullResponse,
    PushRequest,
    PushResponse,
    RevokeResult,
    payload_size,
    row_to_stamp,
    sync_watermark,
)

router = APIRouter(prefix="/api/sync", tags=["sync"])


# ── Yardımcılar ──────────────────────────────────────────────────────────────


def _validate_payload_size(records: List[Any], documents: Dict[str, Any]) -> None:
    """Gövde boyutu sınırını denetler (413)."""
    total = sum(payload_size(record.model_dump()) for record in records)
    total += sum(payload_size(document.model_dump()) for document in documents.values())
    if total > MAX_PAYLOAD_BYTES:
        raise HTTPException(
            status_code=HTTP_413_TOO_LARGE,
            detail="Gönderilen veri çok büyük. Veriyi daha küçük parçalar hâlinde gönderin.",
        )


def _normalize_documents(payload: PushRequest) -> List[DocumentIn]:
    """
    Belge haritasını doğrulanmış listeye çevirir.

    Sözlük anahtarı önceliklidir (`documents: {"theme": {...}}`); gövdedeki
    `doc_type` alanı yalnızca anahtar yoksa kullanılır. İkisi de yoksa 400.
    """
    documents: List[DocumentIn] = []
    for key, document in payload.documents.items():
        doc_type = (key or document.doc_type or "").strip()
        if not doc_type:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Her belge için bir tür adı (doc_type) gereklidir.",
            )
        if doc_type not in DOCUMENT_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Desteklenmeyen belge türü: '{doc_type}'.",
            )
        documents.append(document.model_copy(update={"doc_type": doc_type}))
    return documents


async def _touch_device(db: SupabaseManager, user_id: str, payload: PushRequest) -> None:
    """
    Cihaz envanterini günceller.

    Yalnızca envanter hatası yutulur; `SupabaseConfigurationError` ve
    `PushTooLargeError` yukarı iletilir (503 / 413).
    """
    try:
        await db.touch_device(user_id, payload.device)
    except (SupabaseConfigurationError, PushTooLargeError):
        raise
    except Exception as e:
        debug_log("Cihaz envanteri güncellenemedi:", e)


async def _watermark(db: SupabaseManager) -> str:
    """
    Delta damgasını `updated_at` ile AYNI saat kaynağından alır.

    `updated_at` veritabanının NOW() değeriyle yazılır. Damga API sunucusunun
    saatinden gelirse iki saat arasındaki kayma sessizce kayıp satırlara yol
    açar — ölçülen gerçek kayma ~1 saniye ve bu pencere dolduğunda başka bir
    cihazın yazdığı kayıt bir sonraki `pull?since=` çağrısında hiç gelmez.

    `server_now()` RPC'si tanımlı değilse (DDL çalıştırılmamışsa) saat kayması
    payı kadar geriye giden güvenli yedeğe düşülür ve bir kez uyarı basılır.
    """
    db_time = await db.server_now()
    if db_time:
        return db_time

    _warn_clock_skew_once()
    return sync_watermark()


_warned_clock_skew = False


def _warn_clock_skew_once() -> None:
    """`server_now()` yoksa bir kez görünür uyarı basar."""
    global _warned_clock_skew
    if _warned_clock_skew:
        return
    _warned_clock_skew = True
    konsol.log(
        "[bold yellow][UYARI][/] Veritabanında server_now() fonksiyonu yok — "
        "delta damgası API saatinden ve güvenlik payı kadar geriden alınıyor. "
        "supabase/schema_sync.sql dosyasını çalıştırarak saat kayması riskini "
        "tamamen kaldırın."
    )


async def _mark_pulled(
    db: SupabaseManager, user_id: str, device_id: Optional[str]
) -> None:
    """
    `last_pulled_at` damgasını günceller; hata senkronizasyonu bozmaz.

    `device_id` verilmezse "son push yapan cihaz" (yani `is_current` olan
    satır) kullanılır.
    """
    try:
        await db.mark_pulled(user_id, device_id)
    except Exception as e:
        debug_log("Cihaz çekiş zamanı güncellenemedi:", e)


# ── Endpoint'ler ─────────────────────────────────────────────────────────────


@router.post("/push", summary="Yerel değişiklikleri sunucuya gönder", response_model=PushResponse)
async def push(payload: PushRequest, current_user: CurrentUser):
    """
    Gelen kayıtları ve belgeleri HLC karşılaştırmasıyla uygular.

    200 yanıtı dört liste döner:
      applied            → kabul edilen kayıtlar
      rejected           → reddedilen kayıtlar + sunucu sürümü
      documents_applied  → kabul edilen belge türleri
      documents_rejected → reddedilen belgeler + sunucu sürümü
    """
    if payload.schema_version and payload.schema_version > SUPPORTED_SCHEMA_VERSION:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"İstemci şema sürümü {payload.schema_version}, sunucunun anladığı "
                f"sürüm {SUPPORTED_SCHEMA_VERSION}. Uygulamayı güncelleyin."
            ),
        )

    if len(payload.records) > MAX_RECORDS_PER_PUSH:
        raise HTTPException(
            status_code=HTTP_413_TOO_LARGE,
            detail=(
                f"Tek seferde en fazla {MAX_RECORDS_PER_PUSH} kayıt gönderilebilir. "
                "Veriyi parçalara bölün."
            ),
        )

    if len(payload.documents) > MAX_DOCUMENTS_PER_PUSH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tek seferde en fazla {MAX_DOCUMENTS_PER_PUSH} belge gönderilebilir.",
        )

    documents = _normalize_documents(payload)
    _validate_payload_size(payload.records, payload.documents)

    db = get_supabase_async()

    # 🔴 SU İŞARETİ: yazma işlemlerinden ÖNCE alınır ve `updated_at` ile AYNI
    # saat kaynağından gelir.
    #
    # İstemci bu zamanı bir sonraki `pull?since=` değeri olarak saklar ve
    # karşılaştırma `updated_at > since` ile yapılır:
    #   * Yazmalardan SONRA alınırsa → bu push sırasında başka bir cihazın
    #     yazdığı satırlar (updated_at < damga) hiç gelmez.
    #   * API saatinden alınırsa → DB saati gerideyse aynı sonuç: kayıp satırlar.
    # `_watermark()` ikisini birlikte çözer.
    watermark = await _watermark(db)

    await _touch_device(db, current_user, payload)

    applied, rejected = await db.push_library(current_user, payload.records)
    documents_applied, documents_rejected = await db.push_documents(current_user, documents)

    return PushResponse(
        applied=applied,
        rejected=rejected,
        documents_applied=documents_applied,
        documents_rejected=documents_rejected,
        server_time=watermark,
    )


@router.get("/pull", summary="Sunucudan veri çek", response_model=PullResponse)
async def pull(
    current_user: CurrentUser,
    since: Optional[datetime] = Query(
        default=None,
        description=(
            "Son çekiş zamanı (ISO-8601). Boş bırakılırsa tam döküm döner; "
            "verilirse yalnızca bu sunucu zamanından sonra değişen kayıtlar gelir."
        ),
    ),
    limit: int = Query(
        default=PULL_PAGE_SIZE,
        ge=1,
        le=2000,
        description="Tek yanıtta döndürülecek en fazla kayıt sayısı.",
    ),
    x_device_id: Optional[str] = Header(
        default=None,
        alias="X-Device-Id",
        description=(
            "İsteği yapan cihazın kimliği (opsiyonel). `last_pulled_at` alanını "
            "bu cihaz için günceller."
        ),
    ),
):
    """
    Kullanıcının kayıtlarını ve belgelerini döner.

    İlk girişte `since` gönderilmez → tam döküm. Sonraki çekişlerde
    `since=<son pull zamanı>` gönderilir → delta.

    Tombstone kayıtları da döner; silme bilgisi ancak bu şekilde diğer
    cihazlara ulaşabilir.
    """
    since_iso = _normalize_since(since)
    db = get_supabase_async()

    # 🔴 SU İŞARETİ: hem `_mark_pulled` YAZMASINDAN hem de okumalardan ÖNCE
    # alınır ve `updated_at` ile aynı saat kaynağından gelir (push ile aynı
    # gerekçe). Damga okuma sonrası alınırsa ya da API saatinden alınırsa,
    # okuma sırasında başka bir cihazın yazdığı satırlar bir sonraki çekişte
    # hiç gelmez — sessiz ve kalıcı veri kaybı.
    watermark = await _watermark(db)

    # "Son görülme" bilgisi. `X-Device-Id` gönderilmemişse, bir son push yapan
    # cihaz varsayılır — istemci her döngüde önce pull sonra push yaptığı için
    # bu, cihazın kendisidir.
    await _mark_pulled(db, current_user, x_device_id)

    rows, has_more = await db.fetch_library(current_user, since=since_iso, limit=limit)

    records = [
        PullRecord(
            item_type=row["item_type"],
            content_id=row["content_id"],
            payload=row.get("payload") or {},
            is_deleted=bool(row.get("is_deleted")),
            hlc=row_to_stamp(row),
            device_id=row.get("device_id") or "",
            server_updated_at=row.get("updated_at"),
        )
        for row in rows
    ]

    document_rows = await db.fetch_documents(current_user, since=since_iso, limit=limit)
    documents = {
        row["doc_type"]: PullDocument(
            # ⚠️ `row.get("payload") or {}` BOŞ DİZİYİ NESNEYE ÇEVİRİR:
            # Python'da `[]` falsy'dir, dolayısıyla `[] or {}` -> `{}` olur ve
            # istemci boş arama geçmişini boş NESNE olarak alır. `{}` truthy
            # olduğu için istemcide `payload || []` fallback'i de çalışmaz ve
            # `({}).forEach` undefined döner (birleştirme çöker).
            # `fetch_documents` zaten belge türüne göre normalize ediyor.
            payload=row.get("payload"),
            is_deleted=bool(row.get("is_deleted")),
            hlc=row_to_stamp(row),
            device_id=row.get("device_id") or "",
            server_updated_at=row.get("updated_at"),
        ).model_dump()
        for row in document_rows
    }

    return PullResponse(
        records=records,
        documents=documents,
        deleted_content_ids=[
            record.content_id for record in records if record.is_deleted
        ],
        server_time=watermark,
        has_more=has_more,
    )


@router.get(
    "/devices",
    summary="Bağlı cihazları listele",
    response_model=List[DeviceSummary],
)
async def list_devices(
    current_user: CurrentUser,
    x_device_id: Optional[str] = Header(
        default=None,
        alias="X-Device-Id",
        description="İsteği yapan cihazın kimliği (opsiyonel).",
    ),
):
    """
    Hesaba bağlı, iptal edilmemiş cihazları listeler.

    `is_current` işareti veritabanında "son push yapan cihaz" anlamına gelir.
    `X-Device-Id` başlığı gönderilirse işaret bu cihaza taşınır; bu, aynı anda
    senkronize olan iki cihazın listede doğru işaretlenmesini sağlar.
    """
    db = get_supabase_async()
    rows = await db.list_devices(current_user)

    devices: List[DeviceSummary] = []
    for row in rows:
        device = DeviceSummary(**row)
        if x_device_id:
            device.is_current = device.device_id == x_device_id
        devices.append(device)
    return devices


@router.delete(
    "/devices/{device_id}",
    summary="Cihazın senkronizasyon yetkisini kaldır",
    response_model=RevokeResult,
)
async def revoke_device(device_id: str, current_user: CurrentUser):
    """
    Cihazı iptal eder (`revoked_at` damgalanır) ve listeden düşürür.

    İptal edilen cihazın push yapması kendini geri çağırmaz: `touch_device`
    `revoked_at` alanına dokunmaz.
    """
    if not device_id or len(device_id) > 128:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Geçersiz cihaz kimliği.",
        )

    db = get_supabase_async()
    revoked = await db.revoke_device(current_user, device_id)
    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bu cihaz bulunamadı veya zaten iptal edilmiş.",
        )

    return RevokeResult(
        device_id=device_id,
        revoked=True,
        message="Cihazın senkronizasyon yetkisi kaldırıldı.",
    )


# ── Dahili yardımcılar ───────────────────────────────────────────────────────


def _normalize_since(since: Optional[datetime]) -> Optional[str]:
    """
    `since` parametresini PostgREST'in anladığı ISO-8601 metnine çevirir.

    `updated_at` TIMESTAMPTZ olduğu için saat dilimi bilgisi şarttır; timezone
    yoksa UTC kabul edilir. Karşılaştırma sunucu saatiyle yapılır — cihaz
    saati güvenilmezdir (SYNC_AUTH_PLAN.md §4.4).
    """
    if since is None:
        return None
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    # "+00:00" yerine "Z": sorgu dizesinde `+` kaçış sorunlarına girmesin.
    return since.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )
