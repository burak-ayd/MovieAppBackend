"""
Senkronizasyon sözleşmesi (Pydantic v2) ve HLC karar mantığı.

Bu modül veritabanına bağımlı DEĞİLDİR. Hem API katmanı hem testler saf
fonksiyonları doğrudan çağırabilir; Last-Write-Wins kararının TEK kaynağı
buradır. Karar sunucuda bir kez verildiği için iki cihaz aynı anda push etse
bile sonuç deterministiktir.

Sözleşme: SYNC_AUTH_PLAN.md §4.4 (şema) ve §5.2 (API).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple, Union, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ── Sabitler ────────────────────────────────────────────────────────────────

# user_documents.doc_type için kabul edilen belge türleri.
DOCUMENT_TYPES = (
    "player_settings",
    "search_history",
    "theme",
    "selected_platform",
    "plugin_visibility",
    "category_visibility",
)

# Sunucunun anladığı en yüksek şema sürümü. İstemci daha yüksek sürüm bildirirse
# push reddedilir (400) — sessiz veri bozulmasını engeller.
SUPPORTED_SCHEMA_VERSION = 1

# Güvenlik / kapasite sınırları (§5.3 hata semantiği: 413).
#
# Sınırlar frontend'in gerçek boyut kapaklarına göre seçilmiştir
# (`SIZE_CAPS`: favorite 500 + watchlist 100 + watch_history 50 +
# continue_watching 50 = en fazla 700 kayıt ≈ 400 KB). İstemci her senkronizasyonda
# TÜM yerel durumunu gönderir ve parçalamaz; bu yüzden sınır veri kaybına yol
# açmayacak kadar yüksek, bellek ve kötüye kullanımı sınırlayacak kadar düşük
# tutulmalıdır.
MAX_RECORDS_PER_PUSH = 1000
MAX_DOCUMENTS_PER_PUSH = len(DOCUMENT_TYPES)
MAX_PAYLOAD_BYTES = 2 * 1024 * 1024        # 2 MB
MAX_CONTENT_ID_LENGTH = 512
MAX_DEVICE_ID_LENGTH = 128

# Pull sayfalaması: tek yanıtta döndürülecek en fazla kayıt sayısı.
#
# 🔴 Değer, istemcinin EN BÜYÜK veri kümesini tek sayfada sığdıracak şekilde
# seçilmiştir. Mobil istemci `has_more` alanını yok sayar ve sayfalama YAPMAZ;
# bu yüzden `has_more` true olduğunda 1001+ kayıt hiçbir zaman teslim edilemez.
# `limit` sorgu parametresi daha küçük değerlere indirilebilir — o durumda
# istemci `has_more` için sayfalama sorumluluğu üstlenmelidir.
PULL_PAGE_SIZE = 1000

ItemType = Literal["favorite", "watchlist", "watch_history", "continue_watching"]

# user_library.item_type için geçerli değerler. Literal'dan TÜRETİLİR; DDL'deki
# CHECK kısıtı bu listeyle birebir aynı olmalıdır (tests/test_sync_merge.py).
LIBRARY_ITEM_TYPES = get_args(ItemType)


# ── Ortak taban ─────────────────────────────────────────────────────────────


class JsonModel(BaseModel):
    """
    Repo konvansiyonu: tekli yazdırmada ve listede güzel JSON üret.

    `Core/Plugin/PluginModels.py` her modelde `__str__`/`__repr__` çiftini
    elle yazar; tekrar etmemek için burada bir kez tanımlanıp miras alınır.
    """


    def __str__(self) -> str:
        return self.model_dump_json(indent=4)

    def __repr__(self) -> str:
        return self.__str__()


# ── HLC (Hybrid Logical Clock) ───────────────────────────────────────────────


class HlcStamp(BaseModel):
    """
    Hybrid Logical Clock damgası — istemci ve sunucu arasındaki ortak sözleşme.

    `extra="forbid"` bilinçli bir istisnadır (repo genelinde `extra="allow"`):
    HLC tam olarak `{wall, counter}` olmalıdır; fazla alan sessizce veritabanına
    yazılmamalıdır. İstemci `hlc.toPayload()` yalnızca bu iki alanı gönderir.
    """

    model_config = ConfigDict(extra="forbid")

    wall    : int = Field(ge=0, description="Fiziksel zaman (epoch milisaniye)")
    counter : int = Field(default=0, ge=0, description="Mantıksal sayaç")


HlcInput = Union[HlcStamp, Dict[str, Any]]


def _coerce_hlc(value: HlcInput | None) -> Tuple[int, int]:
    """HLC'yi `(wall, counter)` demetine çevirir; bozuk değerler güvenli sayılır."""
    if value is None:
        return (0, 0)
    if isinstance(value, HlcStamp):
        return (value.wall, value.counter)
    if isinstance(value, dict):
        try:
            return (int(value.get("wall") or 0), int(value.get("counter") or 0))
        except (TypeError, ValueError):
            return (0, 0)
    wall = getattr(value, "wall", 0) or 0
    counter = getattr(value, "counter", 0) or 0
    try:
        return (int(wall), int(counter))
    except (TypeError, ValueError):
        return (0, 0)


def hlc_sort_key(wall: int, counter: int, device_id: Optional[str]) -> Tuple[int, int, str]:
    """
    LWW sıralama anahtarı: (fiziksel zaman, mantıksal sayaç, cihaz kimliği).

    `device_id` son çare eşitlik bozucudur — iki cihaz aynı HLC üretirse
    (nadir ama mümkün) hangisinin kazandığı cihaz kimliğiyle sabitlenir.
    """
    return (int(wall or 0), int(counter or 0), device_id or "")


def compare_hlc(
    a_hlc: HlcInput | None,
    a_device_id: Optional[str],
    b_hlc: HlcInput | None,
    b_device_id: Optional[str],
) -> int:
    """
    İki HLC'yi leksikografik karşılaştırır.

    Dönüş: -1 → a < b, 0 → a == b, +1 → a > b
    """
    a_wall, a_counter = _coerce_hlc(a_hlc)
    b_wall, b_counter = _coerce_hlc(b_hlc)
    return (hlc_sort_key(a_wall, a_counter, a_device_id)
            > hlc_sort_key(b_wall, b_counter, b_device_id)) - (
        hlc_sort_key(a_wall, a_counter, a_device_id)
        < hlc_sort_key(b_wall, b_counter, b_device_id)
    )


def is_incoming_newer(
    incoming_hlc: HlcInput | None,
    incoming_device_id: Optional[str],
    existing_hlc: HlcInput | None,
    existing_device_id: Optional[str],
) -> bool:
    """Gelen sürüm mevcut sürümden yeniyse True. Eşitlikte sunucu korunur (kaybeden cihaz reddedilir)."""
    return compare_hlc(incoming_hlc, incoming_device_id, existing_hlc, existing_device_id) > 0


# ── Yardımcı dönüşümler ─────────────────────────────────────────────────────


def utc_now_iso() -> str:
    """API sunucusunun zaman damgası (ISO-8601, milisaniye)."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# Delta karşılaştırması `updated_at > since` üzerine kuruludur ve `updated_at`
# sütunu VERİTABANININ NOW() değeriyle yazılır. `since` damgası API sunucusunun
# saatinden gelirse, iki saat arasındaki kayma sessizce kayıp satırlara yol
# açar: DB gerideyse, damgadan sonra yazılan satırlar `updated_at > since`
# koşulunu sağlamaz ve bir daha asla teslim edilmez.
#
# Birincil çözüm: damga veritabanından alınır (`server_now()` RPC'si).
# Bu sabit, o RPC kullanılamıyorsa (DDL çalıştırılmamışsa) devreye giren
# GÜVENLİ yedektir: API saatinden bu kadar geriye gidilerek saat kayması
# tolere edilir. Fazlalık güvenlik payı yalnızca birkaç kaydın yeniden
# gelmesine yol açar; HLC birleştirmesi idempotent olduğu için sonuç değişmez.
CLOCK_SKEW_MARGIN_SECONDS = 5


def sync_watermark() -> str:
    """
    API saatine dayalı YEDEK delta damgası (`server_now()` kullanılamıyorsa).

    Saat kayması payı kadar geriye gider; böylece DB saatinin geride olması
    durumunda bile hiçbir satır atlanmaz.
    """
    moment = datetime.now(timezone.utc).timestamp() - CLOCK_SKEW_MARGIN_SECONDS
    return (
        datetime.fromtimestamp(moment, tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def row_to_stamp(row: Dict[str, Any]) -> HlcStamp:
    """Veritabanı satırındaki HLC kolonlarını damgaya çevirir."""
    return HlcStamp(
        wall=int(row.get("hlc_wall") or 0),
        counter=int(row.get("hlc_counter") or 0),
    )


def payload_size(payload: Any) -> int:
    """Yaklaşık JSON bayt boyutu (413 eşiği için)."""
    import json

    try:
        return len(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"))
    except (TypeError, ValueError):
        return 0


# ── Push girdileri ───────────────────────────────────────────────────────────


class DeviceInfo(JsonModel):
    """Push gövdesindeki cihaz kimliği — envanter tablosunun kaynak verisidir."""


    device_id   : str = Field(min_length=1, max_length=MAX_DEVICE_ID_LENGTH)
    device_name : Optional[str] = Field(default=None, max_length=128)
    platform    : Optional[str] = Field(default=None, max_length=32)
    app_version : Optional[str] = Field(default=None, max_length=32)

    @field_validator("device_id", "device_name", "platform", "app_version", mode="before")
    @classmethod
    def _blank_to_none(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("device_id")
    @classmethod
    def _device_id_required(cls, value):
        if not value:
            raise ValueError("device_id boş olamaz.")
        return value


class SyncRecordIn(JsonModel):
    """Kayıt bazlı senkronizasyon girdisi (favori / liste / geçmiş / devam et)."""


    item_type        : ItemType
    content_id       : str = Field(min_length=1, max_length=MAX_CONTENT_ID_LENGTH)
    payload          : Dict[str, Any] = Field(default_factory=dict)
    is_deleted       : bool = False
    hlc              : HlcStamp
    device_id        : str = Field(min_length=1, max_length=MAX_DEVICE_ID_LENGTH)
    client_updated_at: Optional[str] = Field(default=None, max_length=64)

    @field_validator("content_id", mode="before")
    @classmethod
    def _normalize_content_id(cls, value):
        if isinstance(value, (int, float)):
            return str(value)
        return value.strip() if isinstance(value, str) else value

    @field_validator("device_id", mode="before")
    @classmethod
    def _normalize_device_id(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("device_id")
    @classmethod
    def _device_id_required(cls, value):
        if not value:
            raise ValueError("device_id boş olamaz.")
        return value

    @field_validator("payload", mode="before")
    @classmethod
    def _payload_default(cls, value):
        return value if isinstance(value, dict) else {}


class DocumentIn(JsonModel):
    """Belge bazlı senkronizasyon girdisi (ayarlar, tema, görünürlük, ...).

    `doc_type` isteğe bağlıdır: gövdedeki sözlük anahtarı önceliklidir
    (`PushRequest.documents`). Alan gönderilirse anahtarla çelişmemelidir.
    """


    doc_type          : Optional[str] = Field(default=None, max_length=64)
    payload           : Any = Field(default_factory=dict)
    hlc               : HlcStamp
    device_id         : str = Field(min_length=1, max_length=MAX_DEVICE_ID_LENGTH)
    client_updated_at : Optional[str] = Field(default=None, max_length=64)
    is_deleted        : bool = False

    @field_validator("doc_type", mode="before")
    @classmethod
    def _blank_doc_type(cls, value):
        return value.strip() or None if isinstance(value, str) else value

    @field_validator("payload", mode="before")
    @classmethod
    def _payload_default(cls, value):
        return {} if value is None else value

    @field_validator("device_id", mode="before")
    @classmethod
    def _normalize_device_id(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("device_id")
    @classmethod
    def _device_id_required(cls, value):
        if not value:
            raise ValueError("device_id boş olamaz.")
        return value


class PushRequest(JsonModel):
    """POST /api/sync/push gövdesi."""


    device         : DeviceInfo
    records        : List[SyncRecordIn] = Field(default_factory=list)
    documents      : Dict[str, DocumentIn] = Field(default_factory=dict)
    schema_version : Optional[int] = Field(default=None, ge=1)


# ── Push yanıtları ───────────────────────────────────────────────────────────


class AppliedRef(JsonModel):
    """Sunucuya kabul edilen kaydın kimliği."""

    item_type  : ItemType
    content_id : str


class ServerVersion(JsonModel):
    """Sunucudaki güncel sürüm — kaybeden cihazın uzlaştığı için döner."""

    payload           : Any = Field(default_factory=dict)
    is_deleted        : bool = False
    hlc               : HlcStamp
    device_id         : str
    client_updated_at : Optional[str] = None
    server_updated_at : Optional[str] = None


class RejectedRecord(JsonModel):
    """Reddedilen kayıt + sunucu sürümü. Sessiz veri kaybını önler."""

    item_type      : ItemType
    content_id     : str
    reason         : str = Field(description="server_newer | server_equal | schema_unsupported")
    server_version : Optional[ServerVersion] = None


class RejectedDocument(JsonModel):
    """Reddedilen belge + sunucu sürümü."""

    doc_type       : str
    reason         : str
    server_version : Optional[ServerVersion] = None


class PushResponse(JsonModel):
    """POST /api/sync/push 200 gövdesi."""


    applied           : List[AppliedRef] = Field(default_factory=list)
    rejected          : List[RejectedRecord] = Field(default_factory=list)
    documents_applied : List[str] = Field(default_factory=list)
    documents_rejected: List[RejectedDocument] = Field(default_factory=list)
    server_time       : str


# ── Pull yanıtları ───────────────────────────────────────────────────────────


class PullRecord(JsonModel):
    """Tek bir kaydın sunucudaki güncel hali (tombstone dahil)."""


    item_type        : ItemType
    content_id       : str
    payload          : Any = Field(default_factory=dict)
    is_deleted       : bool = False
    hlc              : HlcStamp
    device_id        : str
    server_updated_at: Optional[str] = None


class PullDocument(JsonModel):
    """Tek bir belgenin sunucudaki güncel hali."""


    payload           : Any = Field(default_factory=dict)
    is_deleted        : bool = False
    hlc               : HlcStamp
    device_id         : str
    server_updated_at: Optional[str] = None


class PullResponse(JsonModel):
    """
    GET /api/sync/pull 200 gövdesi.

    `since` yoksa tam döküm, `since` verilmişse delta döner. `has_more` true ise
    istemci aynı `since` ile tekrar çağırmalıdır.
    """


    records            : List[PullRecord] = Field(default_factory=list)
    documents          : Dict[str, PullDocument] = Field(default_factory=dict)
    deleted_content_ids: List[str] = Field(default_factory=list)
    server_time        : str
    has_more           : bool = False


# ── Cihaz uçları ─────────────────────────────────────────────────────────────


class DeviceSummary(JsonModel):
    """user_devices satırının istemciye açılan hâli."""


    device_id    : str
    device_name  : Optional[str] = None
    platform     : Optional[str] = None
    app_version  : Optional[str] = None
    is_current   : bool = False
    last_pulled_at: Optional[str] = None
    last_pushed_at: Optional[str] = None
    revoked_at   : Optional[str] = None
    updated_at   : Optional[str] = None


class RevokeResult(JsonModel):
    """DELETE /api/sync/devices/{device_id} 200 gövdesi."""


    device_id : str
    revoked   : bool
    message   : str
