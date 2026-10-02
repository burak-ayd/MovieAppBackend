"""
Kullanıcı verisi deposu — senkronizasyon ve kimlik doğrulama.

Bu sınıf YALNIZCA kullanıcı verisini yönetir:
    * `user_profiles`   — hesaba bağlı profil alanları
    * `user_library`    — favori / liste / izleme geçmişi / devam et (+ tombstone)
    * `user_documents`  — oynatıcı ayarları, tema, görünürlük, arama geçmişi
    * `user_devices`    — cihaz envanteri

Medya kazıma tabloları (`media`, `sources`, `crawler_state`) bu sınıfın
kapsamı dışındadır; o taraf henüz bağlantı katmanına taşınmadı ve hiçbir
çağıranı yoktur.

Anahtar kullanımı:
    Yalnızca `SUPABASE_SERVICE_ROLE_KEY` kabul edilir. RLS bu tablolarda açık
    ve politika yoktur; anon anahtarla yapılan her sorgu boş döner, her yazma
    reddedilir — HTTP 200 görünürlüğünde senkronizasyon sessizce hiçbir şey
    taşımaz. Bu nedenle yedek anahtar kabul edilmez, açık hata fırlatılır.
    Anahtar istemciye ASLA verilmez; yalnızca sunucuda kalır.

Karar modeli (SYNC_AUTH_PLAN.md §2.2):
    Sunucu tüm otoritelerdir. LWW kararı `(hlc_wall, hlc_counter, device_id)`
    üçlüsüyle merkezî olarak verilir; böylece iki cihaz aynı anda push etse
    bile sonuç deterministiktir.

    Gelen HLC > mevcut HLC → uygula (kazanır)
    Gelen HLC ≤ mevcut HLC → reddet + SUNUCU SÜRÜMÜNÜ DÖNDÜR

Yarış koşulu notu: karar "oku → karar ver → yaz" üç adımıyla verilir. Kaybeden
kayıt hiçbir zaman YAZILMAZ; `rejected` yanıtıyla sunucu sürümü gönderilir ve
kaybeden cihaz uzlaşır. Push gövdesi istemcinin tüm durumunu taşıdığı için
tekrarlanan push'larda hiçbir yazma yapılmaz — çakışma penceresi yalnızca gerçek
an eşzamanlı iki push'ta açılır.

Sınıf adı (`SupabaseManager`) korunmuştur: `PLAN.md:39` adı yanlış gösteriyor
olsa da sekiz import noktası bu ada bağlıdır.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from supabase import AsyncClient, acreate_client

from Core.Helpers.Cli import debug_log
from Core.Libs.SupabaseAuth import resolve_service_role_key, resolve_supabase_url
from Core.Libs.SyncModels import (
    MAX_DOCUMENTS_PER_PUSH,
    PULL_PAGE_SIZE,
    DeviceInfo,
    DocumentIn,
    SyncRecordIn,
    compare_hlc,
    is_incoming_newer,
    normalize_document_payload,
    row_to_stamp,
    utc_now_iso,
)


class SupabaseConfigurationError(RuntimeError):
    """Supabase bağlantı bilgileri eksik."""


class PushTooLargeError(RuntimeError):
    """
    Karar için okunan kayıtlar tavana dayandı.

    HLC kararı tüm mevcut sürümlerle karşılaştırma yapmadan verilemez; okuma
    doymuşsa sessiz ezme yerine hata fırlatılır.
    """


# Sunucu sürümünü istemciye dönerken kullanılan kolonlar.
_LIBRARY_COLUMNS = (
    "item_type,content_id,payload,is_deleted,hlc_wall,hlc_counter,"
    "device_id,client_updated_at,updated_at"
)
_DOCUMENT_COLUMNS = (
    "doc_type,payload,is_deleted,hlc_wall,hlc_counter,"
    "device_id,client_updated_at,updated_at"
)
_DEVICE_COLUMNS = (
    "device_id,device_name,platform,app_version,is_current,"
    "last_pulled_at,last_pushed_at,revoked_at,updated_at"
)

# Push kararı için okunacak azami satır sayısı. Yerel veri küçük olduğu için
# pratikte tüm kullanıcı kütüphanesi okunur; bu sınır yalnızca PostgREST'in
# sunucu tarafı satır sınırına güvenlik ağıdır.
PUSH_COMPARE_LIMIT = 5000

# Tek PostgREST isteğinde gönderilecek azami satır sayısı.
_UPSERT_CHUNK_SIZE = 200


class SupabaseManager:
    """Kullanıcı verisi erişim noktası (async)."""

    def __init__(self) -> None:
        self._async_client: Optional[AsyncClient] = None

    # ══════════════════════════════════════════════════════════════════════════
    # İstemci
    # ══════════════════════════════════════════════════════════════════════════

    async def async_client(self) -> AsyncClient:
        """
        Async istemciyi döndürür (lazy singleton).

        🔴 Servis rolü anahtarı ZORUNLUDUR. `user_library` / `user_documents`
        tablolarında RLS açık ve politika YOKTUR; anon anahtarla yapılan her
        sorgu boş döner, her yazma reddedilir — HTTP 200 görünürlüğünde
        SENKRONİZASYON SESSİZCE ÇALIŞMAZ. Yedek anahtar kabul edilmez, açık bir
        hata fırlatılır.
        """
        if self._async_client is None:
            url = resolve_supabase_url()
            key, _ = resolve_service_role_key()
            if not url:
                raise SupabaseConfigurationError(
                    "SUPABASE_URL tanımlı değil. .env dosyasını kontrol edin."
                )
            if not key:
                raise SupabaseConfigurationError(
                    "SUPABASE_SERVICE_ROLE_KEY tanımlı değil. RLS açık "
                    "user_library / user_documents tablolarına servis rolü olmadan "
                    "erişilemez."
                )
            self._async_client = await acreate_client(url, key)
        return self._async_client

    async def close_async(self) -> None:
        """Açık HTTP bağlantılarını kapatır (lifespan shutdown)."""
        if self._async_client is not None:
            try:
                await self._async_client.postgrest.aclose()
            except Exception as e:
                debug_log("Supabase async istemci kapatılırken hata:", e)
            self._async_client = None

    async def server_now(self) -> Optional[str]:
        """
        Veritabanının kendi saatini döndürür (ISO-8601), yoksa None.

        `updated_at` sütunu veritabanının NOW() değeriyle yazılır. Delta
        karşılaştırması (`updated_at > since`) bu nedenle AYNI saat kaynağından
        gelen bir damga gerektirir; API sunucusunun saati kullanılırsa iki saat
        arasındaki kayma sessizce kayıp satırlara yol açar.

        `server_now()` RPC'si `supabase/schema_sync.sql` ile oluşturulur.
        Projede tanımlı değilse None döner; çağıran `sync_watermark()` yedeğine
        düşmelidir.
        """
        client = await self.async_client()
        try:
            result = await client.rpc("server_now").execute()
        except Exception as e:
            debug_log("server_now() çağrısı başarısız (yedek damga kullanılacak):", e)
            return None

        return _iso_utc(_unwrap_rpc_value(result.data))

    # ── Profil ───────────────────────────────────────────────────────────────

    async def get_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Kullanıcının profil satırını okur; yoksa None."""
        client = await self.async_client()
        result = await client.table("user_profiles").select("*").eq("id", user_id).limit(1).execute()
        return result.data[0] if result.data else None

    async def username_taken(self, username: str, exclude_user_id: Optional[str] = None) -> bool:
        """
        Kullanıcı adı alınmış mı?

        `user_profiles.username` UNIQUE; sorgu kullanıcıya göre filtrelenmez
        çünkü benzersizlik global olmalıdır.
        """
        client = await self.async_client()
        query = client.table("user_profiles").select("id").eq("username", username).limit(1)
        if exclude_user_id:
            query = query.neq("id", exclude_user_id)
        result = await query.execute()
        return bool(result.data)

    async def create_profile(
        self,
        user_id: str,
        username: str,
        display_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Yeni kullanıcı için profil satırı oluşturur.

        E-posta bilinçli olarak burada tutulmaz: kimlik `auth.users` tablosunda
        ve JWT iddiaları üzerinden gelir (tek kopya ilkesi).
        """
        client = await self.async_client()
        result = await (
            client.table("user_profiles")
            .upsert(
                {
                    "id": user_id,
                    "username": username,
                    "display_name": display_name or username,
                },
                on_conflict="id",
            )
            .execute()
        )
        return result.data[0] if result.data else {}

    async def update_profile(self, user_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        """
        Profil alanlarını günceller. `updated_at` tetikleyicisi devrede.

        ⚠️ Henüz bir uç bu metodu çağırmıyor; profil düzenleme endpoint'i
        SYNC_AUTH_PLAN.md §5.1'de yok. Şema hazır bekliyor.
        """
        client = await self.async_client()
        result = await (
            client.table("user_profiles").update(fields).eq("id", user_id).execute()
        )
        return result.data[0] if result.data else {}

    # ── Kütüphane (kayıt bazlı) ───────────────────────────────────────────────

    async def fetch_library(
        self,
        user_id: str,
        item_types: Optional[List[str]] = None,
        since: Optional[str] = None,
        limit: int = PULL_PAGE_SIZE,
    ) -> Tuple[List[Dict[str, Any]], bool]:
        """
        Kullanıcının kayıtlarını okur.

        Dönüş: `(satırlar, has_more)`. `since` verilmişse yalnızca o sunucu
        zamanından sonra değişen satırlar döner (delta). Tombstone satırları da
        dahildir — silmenin diğer cihazlara ulaşması bunlarla sağlanır.

        `user_id` filtresi HER sorguda zorunludur; kullanıcı izolasyonunun tek
        güvencesi budur.
        """
        client = await self.async_client()
        query = (
            client.table("user_library")
            .select(_LIBRARY_COLUMNS)
            .eq("user_id", user_id)
            .order("updated_at", desc=False)
            .order("id", desc=False)
            .limit(limit + 1)
        )
        if item_types:
            query = query.in_("item_type", item_types)
        if since:
            query = query.gt("updated_at", since)

        result = await query.execute()
        rows = result.data or []
        has_more = len(rows) > limit
        return rows[:limit], has_more

    async def push_library(
        self, user_id: str, records: List[SyncRecordIn]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Kayıtları koşullu olarak uygular (LWW).

        Dönüş: `(uygulanan, reddedilen)`. Reddedilen kayıtlar sunucu sürümünü
        taşır — kaybeden cihaz sessizce veri kaybetmez, uzlaştırır.

        Aynı `(item_type, content_id)` için gelen çoklu kayıtlar HLC'ye göre
        tekilleştirilir; böylece giriş sırası sonucu etkilemez.
        """
        if not records:
            return [], []

        unique = _dedupe_records(records)
        item_types = sorted({record.item_type for record in unique.values()})

        # Karar için kullanıcının TÜM ilgili kayıtları okunur; yalnızca gelen
        # anahtarlar okunursa sunucudaki bir satır gözden kaçıp ezilebilirdi.
        existing_rows, has_more = await self.fetch_library(
            user_id, item_types=item_types, limit=PUSH_COMPARE_LIMIT
        )
        if has_more:
            # Okuma doymuşsa `existing` eksiktir; karar eksik bilgiyle verilirse
            # satırlar HLC karşılaştırması YAPILMADAN ezilir. Bu, modülün
            # temel garantisini ihlal eden sessiz veri kaybıdır; yüksek sesle
            # hata verilir.
            raise PushTooLargeError(
                f"Kullanıcının {PUSH_COMPARE_LIMIT} kaydı aşan bir kütüphanesi var. "
                "Veriyi küçültüp tekrar deneyin."
            )

        existing: Dict[Tuple[str, str], Dict[str, Any]] = {
            (row["item_type"], row["content_id"]): row for row in existing_rows
        }

        to_write: List[Dict[str, Any]] = []
        rejected: List[Dict[str, Any]] = []

        for (item_type, content_id), record in unique.items():
            row = existing.get((item_type, content_id))
            if row is None:
                to_write.append(_library_row(user_id, record))
                continue

            verdict = compare_hlc(
                record.hlc, record.device_id, row_to_stamp(row), row.get("device_id")
            )
            if verdict > 0:
                to_write.append(_library_row(user_id, record))
            else:
                rejected.append(
                    {
                        "item_type": item_type,
                        "content_id": content_id,
                        "reason": "server_equal" if verdict == 0 else "server_newer",
                        "server_version": _server_version(row),
                    }
                )

        if to_write:
            await self._upsert_chunks(
                "user_library", to_write, on_conflict="user_id,item_type,content_id"
            )

        return (
            [
                {"item_type": row["item_type"], "content_id": row["content_id"]}
                for row in to_write
            ],
            rejected,
        )

    # ── Belgeler (belge bazlı) ───────────────────────────────────────────────

    async def fetch_documents(
        self,
        user_id: str,
        since: Optional[str] = None,
        limit: int = MAX_DOCUMENTS_PER_PUSH,
    ) -> List[Dict[str, Any]]:
        """
        Kullanıcının belgelerini okur; `since` verilmişse delta döner.

        `limit` tüm belge türlerini kapsar: `doc_type` başına tek satır tutulduğu
        için `MAX_DOCUMENTS_PER_PUSH` (belge türü sayısı) tavanı yeterlidir ve
        sessiz kırpma olmaz.
        """
        client = await self.async_client()
        query = (
            client.table("user_documents")
            .select(_DOCUMENT_COLUMNS)
            .eq("user_id", user_id)
            .order("updated_at", desc=False)
            .limit(limit)
        )
        if since:
            query = query.gt("updated_at", since)
        result = await query.execute()
        rows = result.data or []

        # Boş JSONB dizi `{}` olarak gelebilir (bkz. normalize_document_payload).
        # Sözleşmeyi burada sabitliyoruz: istenci türü doğru şekilde alır.
        for row in rows:
            row["payload"] = normalize_document_payload(
                row.get("doc_type"), row.get("payload")
            )
        return rows

    async def push_documents(
        self, user_id: str, documents: List[DocumentIn]
    ) -> Tuple[List[str], List[Dict[str, Any]]]:
        """
        Belgeleri koşullu olarak uygular (LWW).

        Dönüş: `(uygulanan_doc_type_listesi, reddedilen_listesi)`.
        """
        if not documents:
            return [], []

        unique: Dict[str, DocumentIn] = {}
        for document in documents:
            current = unique.get(document.doc_type)
            if current is None or is_incoming_newer(
                document.hlc, document.device_id, current.hlc, current.device_id
            ):
                unique[document.doc_type] = document

        rows = await self.fetch_documents(user_id)
        existing = {row["doc_type"]: row for row in rows}

        to_write: List[Dict[str, Any]] = []
        rejected: List[Dict[str, Any]] = []

        for doc_type, document in unique.items():
            row = existing.get(doc_type)
            if row is None:
                to_write.append(_document_row(user_id, document))
                continue

            verdict = compare_hlc(
                document.hlc, document.device_id, row_to_stamp(row), row.get("device_id")
            )
            if verdict > 0:
                to_write.append(_document_row(user_id, document))
            else:
                rejected.append(
                    {
                        "doc_type": doc_type,
                        "reason": "server_equal" if verdict == 0 else "server_newer",
                        "server_version": _server_version(row),
                    }
                )

        if to_write:
            await self._upsert_chunks("user_documents", to_write, on_conflict="user_id,doc_type")

        return [row["doc_type"] for row in to_write], rejected

    # ── Cihaz envanteri ──────────────────────────────────────────────────────

    async def touch_device(self, user_id: str, device: DeviceInfo) -> None:
        """
        Cihazı envantere kaydeder ve "bu cihaz" işaretini taşır.

        `revoked_at` bilinçli olarak TEMİZLENMEZ: iptal edilen bir cihaz
        tekrar push ederek kendini geri çağıramaz.
        """
        client = await self.async_client()
        await (
            client.table("user_devices")
            .upsert(
                {
                    "user_id": user_id,
                    "device_id": device.device_id,
                    "device_name": device.device_name,
                    "platform": device.platform,
                    "app_version": device.app_version,
                    "is_current": True,
                    "last_pushed_at": utc_now_iso(),
                },
                on_conflict="user_id,device_id",
            )
            .execute()
        )
        # Diğer cihazların "bu cihaz" işareti kaldırılır.
        await (
            client.table("user_devices")
            .update({"is_current": False})
            .eq("user_id", user_id)
            .neq("device_id", device.device_id)
            .eq("is_current", True)
            .execute()
        )

    async def mark_pulled(self, user_id: str, device_id: Optional[str] = None) -> bool:
        """
        Cihazın son çekiş zamanını günceller.

        `device_id` verilmezse "son push yapan cihaz" (`is_current = true`)
        hedeflenir; pull isteğinde istemci cihaz kimliğini `X-Device-Id` başlığıyla
        bildirebilir. Başarılıysa True döner.
        """
        client = await self.async_client()
        query = client.table("user_devices").update(
            {"last_pulled_at": utc_now_iso()}
        ).eq("user_id", user_id)
        if device_id:
            query = query.eq("device_id", device_id)
        else:
            query = query.eq("is_current", True)
        result = await query.execute()
        return bool(result.data)

    async def list_devices(self, user_id: str) -> List[Dict[str, Any]]:
        """Bağlı ve iptal edilmemiş cihazları listeler (en son kullanılan önce)."""
        client = await self.async_client()
        result = await (
            client.table("user_devices")
            .select(_DEVICE_COLUMNS)
            .eq("user_id", user_id)
            .is_("revoked_at", None)
            .order("last_pushed_at", desc=True, nullsfirst=False)
            .execute()
        )
        return result.data or []

    async def revoke_device(self, user_id: str, device_id: str) -> bool:
        """
        Cihazı iptal eder. Bulunamazsa veya ZATEN iptal edilmişse False döner.

        `revoked_at IS NULL` filtresi işlemi idempotent kılar ve 404 mesajındaki
        "zaten iptal edilmiş" ifadesini doğru kılar.
        """
        client = await self.async_client()
        result = await (
            client.table("user_devices")
            .update({"revoked_at": utc_now_iso(), "is_current": False})
            .eq("user_id", user_id)
            .eq("device_id", device_id)
            .is_("revoked_at", None)
            .execute()
        )
        return bool(result.data)

    # ── Düşük seviye yardımcılar ─────────────────────────────────────────────

    async def _upsert_chunks(
        self, table: str, rows: List[Dict[str, Any]], on_conflict: str
    ) -> None:
        """
        Toplu upsert. Gövde tek istekte gönderilmez.

        `on_conflict` verildiği için Postgres `ON CONFLICT ... DO UPDATE`
        çalıştırır; aynı anahtar için 23505 üretilmez. 200 satırlık parçalar mobil
        bağlantıyı ve PostgREST gövde sınırını rahatlatır.
        """
        client = await self.async_client()
        for start in range(0, len(rows), _UPSERT_CHUNK_SIZE):
            chunk = rows[start:start + _UPSERT_CHUNK_SIZE]
            await client.table(table).upsert(chunk, on_conflict=on_conflict).execute()


# ══════════════════════════════════════════════════════════════════════════════
# Saf dönüşüm yardımcıları (test edilebilir olması için modül düzeyinde)
# ══════════════════════════════════════════════════════════════════════════════


def _unwrap_rpc_value(data: Any) -> Any:
    """
    PostgREST RPC yanıtını tek değere indirger.

    ⚠️ PostgREST, tek satır / tek sütun döndüren bir fonksiyon için yanıtı
    **çıplak bir JSON değeri** olarak verir, liste olarak DEĞİL. Yani
    `SELECT NOW()` için `data` doğrudan `"2026-10-01T12:00:00+00:00"` metnidir.
    `data[0]` yazmak listenin ilk elemanı yerine metnin İLK KARAKTERİNİ döndürür —
    sessizce `server_time = "2"` gibi çarpık bir damga üretir ve delta senkronizasyonu
    1970'a kayarak sürekli tam döküm yapar.
    """
    if isinstance(data, list):
        return data[0] if data else None
    return data


def _iso_utc(value: Any) -> Optional[str]:
    """
    Postgres'ten dönen timestamptz değerini ISO-8601 UTC metnine çevirir.

    Postgres mikro saniye döner; API sözleşmesi milisaniye kullanır. Fazlalık
    hassasiyet atılır — karşılaştırma zaten veritabanında yapıldığı için
    bilgi kaybı olmaz, yalnızca metin kısalır.
    """
    if value is None:
        return None

    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return (
            moment.astimezone(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )

    # postgrest bazen metin döner; yalnızca UTC işaretini normalize ederiz.
    return str(value).replace("+00:00", "Z")


def _dedupe_records(
    records: List[SyncRecordIn],
) -> Dict[Tuple[str, str], SyncRecordIn]:
    """
    Aynı anahtarı taşıyan kayıtları en yeni HLC'ye göre tekilleştirir.

    Giriş sırasından bağımsız sonuç verir — sıra bağımsızlığının sunucu
    tarafındaki karşılığı budur.
    """
    unique: Dict[Tuple[str, str], SyncRecordIn] = {}
    for record in records:
        key = (record.item_type, record.content_id)
        current = unique.get(key)
        if current is None or is_incoming_newer(
            record.hlc, record.device_id, current.hlc, current.device_id
        ):
            unique[key] = record
    return unique


def _library_row(user_id: str, record: SyncRecordIn) -> Dict[str, Any]:
    """Gelen kaydı veritabanı satırına çevirir."""
    return {
        "user_id": user_id,
        "item_type": record.item_type,
        "content_id": record.content_id,
        "payload": record.payload,
        "is_deleted": bool(record.is_deleted),
        "hlc_wall": record.hlc.wall,
        "hlc_counter": record.hlc.counter,
        "device_id": record.device_id,
        "client_updated_at": record.client_updated_at,
    }


def _document_row(user_id: str, document: DocumentIn) -> Dict[str, Any]:
    """Gelen belgeyi veritabanı satırına çevirir."""
    return {
        "user_id": user_id,
        "doc_type": document.doc_type,
        "payload": document.payload,
        "is_deleted": bool(document.is_deleted),
        "hlc_wall": document.hlc.wall,
        "hlc_counter": document.hlc.counter,
        "device_id": document.device_id,
        "client_updated_at": document.client_updated_at,
    }


def _server_version(row: Dict[str, Any]) -> Dict[str, Any]:
    """Sunucu satırını istemcinin beklediği `server_version` biçimine çevirir."""
    stamp = row_to_stamp(row)
    payload = row.get("payload")
    if payload is None:
        payload = {}
    return {
        # Reddedilen belgenin `doc_type`'ı satırda bulunur; liste türleri için
        # boş JSONB dizi `{}` olarak gelmiş olabilir, düzeltilir.
        "payload": normalize_document_payload(row.get("doc_type"), payload),
        "is_deleted": bool(row.get("is_deleted")),
        "hlc": {"wall": stamp.wall, "counter": stamp.counter},
        "device_id": row.get("device_id") or "",
        "client_updated_at": row.get("client_updated_at"),
        "server_updated_at": row.get("updated_at"),
    }
