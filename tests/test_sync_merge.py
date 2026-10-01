"""
Senkronizasyon test paketi — saf ve ağsız.

Kapsam (SYNC_AUTH_PLAN.md §8.2):
  * HLC karar mantığı: sıra bağımsızlığı, saat farkı, eşitlik bozucu
  * Koşullu upsert: tekrar push → rejected, iki cihaz yarışı → deterministik
  * Delta çekme: `since` yalnızca değişen kayıtları döner
  * `user_id` izolasyonu: A'nın verisi B'ye görünmez  🔴 kritik
  * Sürüm uyuşmazlığı → 400

Test iki katmanlıdır:
  1. **Saf fonksiyon testleri** — `compare_hlc`, `_dedupe_records`, `_server_version`
     vb. Veritabanı yoktur, en düşük risk.
  2. **Depo testleri** — `SupabaseManager` async metotları, bellek içi sahte
     PostgREST istemcisi ile. Bu katman, metotların ürettiği sorgu
     koşullarının (özellikle `user_id` filtresinin) doğru olduğunu kanıtlar.
"""

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from Core.Libs.Supabase import (
    _DEVICE_COLUMNS,
    _DOCUMENT_COLUMNS,
    _LIBRARY_COLUMNS,
    SupabaseManager,
    _dedupe_records,
    _document_row,
    _library_row,
    _server_version,
)
from Core.Libs.SyncModels import (
    LIBRARY_ITEM_TYPES,
    DeviceInfo,
    DocumentIn,
    HlcStamp,
    SyncRecordIn,
    compare_hlc,
    is_incoming_newer,
    row_to_stamp,
    utc_now_iso,
)


# ══════════════════════════════════════════════════════════════════════════════
# Bellek içi sahte PostgREST istemcisi
# ══════════════════════════════════════════════════════════════════════════════


# Gerçek veritabanındaki `set_updated_at()` tetikleyicisini taklit eden tek
# yönlü saat. Delta (`gt updated_at`) testleri buna dayanır.
_CLOCK = {"last": 0.0}


def _next_updated_at():
    now = time.time()
    _CLOCK["last"] = max(now, _CLOCK["last"] + 0.001)
    return _iso_from_timestamp(_CLOCK["last"])


def fake_checkpoint():
    """
    Sahte saatin şu anki değerini döner.

    Delta testlerinde `since` referansı olarak kullanılır. Gerçek `datetime.now()`
    ile `time.time()` farklı hassasiyetlerde çalıştığı için ikisi karşılaştırılamaz;
    sahte saatin tek kaynak olarak kullanılması testleri kararlı kılar.
    """
    return _iso_from_timestamp(_CLOCK["last"])


def _iso_from_timestamp(value):
    return (
        datetime.fromtimestamp(value, tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    """PostgREST sorgu oluşturucusunun kullandığı alt kümeni taklit eder."""

    def __init__(self, table_name, store, columns=None, filters=None, operation="select",
                 payload=None, on_conflict=None, orders=None, limit=None):
        self._table_name = table_name
        self._store = store
        self._columns = columns
        self._filters = filters or {}
        self._operation = operation
        self._payload = payload
        self._on_conflict = on_conflict
        self._orders = orders or []
        self._limit = limit

    def _clone(self, **overrides):
        """Tüm zincir durumunu koruyan kopya (filtre/sıra/sınır kaybı olmaz)."""
        state = {
            "columns": self._columns,
            "filters": self._filters,
            "operation": self._operation,
            "payload": self._payload,
            "on_conflict": self._on_conflict,
            "orders": self._orders,
            "limit": self._limit,
        }
        state.update(overrides)
        return FakeQuery(self._table_name, self._store, **state)

    # ── Filtreler ──
    def eq(self, column, value):
        return self._with(column, "eq", value)

    def neq(self, column, value):
        return self._with(column, "neq", value)

    def gt(self, column, value):
        return self._with(column, "gt", value)

    def in_(self, column, values):
        return self._with(column, "in", list(values))

    def is_(self, column, value):
        return self._with(column, "is", value)

    def _with(self, column, operator, value):
        filters = {key: list(conditions) for key, conditions in self._filters.items()}
        filters.setdefault(column, []).append((operator, value))
        return self._clone(filters=filters)

    # ── Zincirleme ──
    def order(self, column, desc=False, nullsfirst=None):
        return self._clone(orders=list(self._orders) + [(column, desc)])

    def limit(self, count):
        return self._clone(limit=count)

    def select(self, columns):
        return self._clone(columns=columns)

    # ── Yürütme ──
    async def execute(self):
        stored = self._store.setdefault(self._table_name, [])
        matched = [row for row in stored if self._matches(row)]

        if self._operation == "upsert":
            self._apply_upsert(stored)
            return FakeResponse(matched)
        if self._operation == "update":
            for row in matched:
                row.update(self._payload)
                row["updated_at"] = _next_updated_at()
            return FakeResponse(matched)

        rows = self._sorted(matched)
        if self._limit is not None:
            rows = rows[: self._limit]
        if self._columns and self._columns != "*":
            wanted = [key.strip() for key in self._columns.split(",")]
            rows = [{key: row.get(key) for key in wanted if key in row} for row in rows]
        return FakeResponse(rows)

    def _matches(self, row):
        for column, conditions in self._filters.items():
            value = row.get(column)
            for operator, expected in conditions:
                if operator == "eq" and value != expected:
                    return False
                if operator == "neq" and value == expected:
                    return False
                if operator == "gt" and not (value is not None and str(value) > str(expected)):
                    return False
                if operator == "in" and value not in expected:
                    return False
                if operator == "is" and value is not None:
                    return False
        return True

    def _sorted(self, rows):
        rows = list(rows)
        for column, desc in reversed(self._orders):
            rows.sort(
                key=lambda r: (r.get(column) is not None, str(r.get(column) or "")),
                reverse=desc,
            )
        return rows

    def _apply_upsert(self, store):
        """Basit ON CONFLICT DO UPDATE taklidi (+ updated_at tetikleyicisi)."""
        rows = self._payload if isinstance(self._payload, list) else [self._payload]
        key_columns = self._on_conflict.split(",") if self._on_conflict else []
        for row in rows:
            match = None
            if key_columns:
                for candidate in store:
                    if all(candidate.get(c) == row.get(c) for c in key_columns):
                        match = candidate
                        break
            if match is not None:
                match.update(row)
            else:
                row = dict(row)
                row["updated_at"] = _next_updated_at()
                store.append(row)
            # BEFORE UPDATE tetikleyicisi gibi updated_at tazelenir.
            match_row = match if match is not None else store[-1]
            match_row["updated_at"] = _next_updated_at()


class FakeClient:
    def __init__(self):
        self.store = {}

    def table(self, name):
        store = self.store

        class _Builder:
            def select(self, columns):
                return FakeQuery(name, store, columns)

            def upsert(self, payload, on_conflict=""):
                return FakeQuery(name, store, operation="upsert",
                                 payload=payload, on_conflict=on_conflict)

            def update(self, payload):
                return FakeQuery(name, store, operation="update", payload=payload)

        return _Builder()


def make_manager(store):
    """Sahte async istemciye bağlı bir SupabaseManager üretir."""
    manager = SupabaseManager()
    client = FakeClient()
    client.store = store

    async def async_client():
        return client

    manager.async_client = async_client  # type: ignore[method-assign]
    manager._fake_client = client  # type: ignore[attr-defined]
    return manager


# ══════════════════════════════════════════════════════════════════════════════
# 1. HLC KARAR MANTIĞI (saf)
# ══════════════════════════════════════════════════════════════════════════════


class TestHlcComparison:
    """Last-Write-Wins sıralama anahtarı: (wall, counter, device_id)."""

    def test_fiziksel_zaman_kazanır(self):
        assert compare_hlc({"wall": 200, "counter": 0}, "a",
                           {"wall": 100, "counter": 0}, "b") > 0

    def test_sayac_kazanır(self):
        assert compare_hlc({"wall": 100, "counter": 5}, "a",
                           {"wall": 100, "counter": 2}, "b") > 0

    def test_esitlik_bozucu_cihaz_kimligi(self):
        """Aynı HLC'de leksikografik büyük cihaz kazanır — karar sabittir."""
        assert compare_hlc({"wall": 100, "counter": 3}, "cihaz-b",
                           {"wall": 100, "counter": 3}, "cihaz-a") > 0
        assert compare_hlc({"wall": 100, "counter": 3}, "cihaz-a",
                           {"wall": 100, "counter": 3}, "cihaz-b") < 0

    def test_tam_esitlik_sifir_dondurur(self):
        assert compare_hlc({"wall": 1, "counter": 1}, "x",
                           {"wall": 1, "counter": 1}, "x") == 0

    def test_bozuk_hlc_sifir_sayilir(self):
        assert compare_hlc(None, "a", {"wall": 5, "counter": 0}, "b") < 0
        assert compare_hlc({"wall": 5, "counter": 0}, "b", None, "a") > 0

    def test_saat_farki_senaryosu(self):
        """
        Saat farkı senaryosu (SYNC_AUTH_PLAN.md §2.3).

        Tablet 5 dk ileri saatte yazdı (wall=10:06), telefon gerçek zamanda
        yazdı (wall=10:03). Aynı anda iki cihazdan gelen kayıt arasında
        karar deterministiktir; hangisi gelirse gelsin aynı sonuç çıkar.
        """
        tablet = ({"wall": 1006, "counter": 0}, "tablet")
        telefon = ({"wall": 1003, "counter": 0}, "telefon")

        assert is_incoming_newer(*tablet, *telefon) is True
        assert is_incoming_newer(*telefon, *tablet) is False
        # Karşı yön de aynı sonucu verir → sıra bağımsız.
        assert is_incoming_newer(*telefon, *tablet) != is_incoming_newer(*tablet, *telefon)


class TestDedupe:
    """Aynı anahtarı taşıyan çoklu kayıtlar HLC'ye göre tekilleştirilir."""

    @staticmethod
    def _record(content_id, wall, counter=0, device="telefon"):
        return SyncRecordIn(
            item_type="favorite",
            content_id=content_id,
            payload={"title": content_id},
            hlc=HlcStamp(wall=wall, counter=counter),
            device_id=device,
        )

    def test_en_yenik_ve_ilk_sezilir(self):
        records = [
            self._record("a", 100),
            self._record("a", 300),
            self._record("a", 200),
        ]
        unique = _dedupe_records(records)
        assert len(unique) == 1
        assert unique[("favorite", "a")].hlc.wall == 300

    def test_sira_bagimsiz(self):
        ilk = _dedupe_records([self._record("a", 100), self._record("a", 300)])
        son = _dedupe_records([self._record("a", 300), self._record("a", 100)])
        assert ilk[("favorite", "a")].hlc == son[("favorite", "a")].hlc

    def test_farkli_anahtarlar_korunur(self):
        records = [self._record("a", 100), self._record("b", 100)]
        assert len(_dedupe_records(records)) == 2


class TestServerVersion:
    """Sunucu sürümü istemcinin beklediği biçime çevrilir."""

    def test_bicim(self):
        row = {
            "payload": {"title": "Inception"},
            "is_deleted": True,
            "hlc_wall": 1760000009999,
            "hlc_counter": 7,
            "device_id": "başka-cihaz",
            "client_updated_at": "2026-10-01T12:00:00.000Z",
            "updated_at": "2026-10-01T12:00:05.000Z",
        }
        version = _server_version(row)
        assert version["hlc"] == {"wall": 1760000009999, "counter": 7}
        assert version["device_id"] == "başka-cihaz"
        assert version["is_deleted"] is True
        assert version["payload"] == {"title": "Inception"}
        assert version["server_updated_at"] == "2026-10-01T12:00:05.000Z"


# ══════════════════════════════════════════════════════════════════════════════
# 2. KAYIT BAZLI KOŞULLU UPSERT
# ══════════════════════════════════════════════════════════════════════════════


def make_record(content_id, wall, counter=0, device="telefon", item_type="favorite",
                is_deleted=False, title=None):
    return SyncRecordIn(
        item_type=item_type,
        content_id=content_id,
        payload={"title": title or content_id},
        is_deleted=is_deleted,
        hlc=HlcStamp(wall=wall, counter=counter),
        device_id=device,
        client_updated_at=utc_now_iso(),
    )


@pytest.mark.asyncio
class TestPushLibrary:
    """POST /api/sync/push — kayıt bazlı LWW."""

    async def test_bos_durumda_bos_sonuc(self):
        manager = make_manager({})
        applied, rejected = await manager.push_library("user-a", [])
        assert applied == [] and rejected == []

    async def test_ilk_push_uygular(self):
        manager = make_manager({})
        applied, rejected = await manager.push_library(
            "user-a", [make_record("abc", 1000)]
        )
        assert applied == [{"item_type": "favorite", "content_id": "abc"}]
        assert rejected == []
        assert manager._fake_client.store["user_library"][0]["payload"] == {"title": "abc"}

    async def test_ayni_kaydi_tekrar_push_rejected(self):
        """Aynı kayıt ikinci kez gönderilirse reddedilir ve sunucu sürümü döner."""
        manager = make_manager({})
        record = make_record("abc", 1000, title="Inception")
        await manager.push_library("user-a", [record])

        applied, rejected = await manager.push_library("user-a", [record])
        assert applied == []
        assert len(rejected) == 1
        assert rejected[0]["reason"] == "server_equal"
        assert rejected[0]["server_version"]["payload"] == {"title": "Inception"}

    async def test_daha_eski_kayit_reddedilir(self):
        manager = make_manager({})
        await manager.push_library("user-a", [make_record("abc", 2000, device="tablet")])
        applied, rejected = await manager.push_library(
            "user-a", [make_record("abc", 1000, device="telefon")]
        )
        assert applied == []
        assert rejected[0]["reason"] == "server_newer"
        assert rejected[0]["server_version"]["device_id"] == "tablet"

    async def test_daha_yeni_kayit_uygular(self):
        manager = make_manager({})
        await manager.push_library("user-a", [make_record("abc", 1000, device="telefon")])
        applied, rejected = await manager.push_library(
            "user-a", [make_record("abc", 3000, device="tablet")]
        )
        assert applied == [{"item_type": "favorite", "content_id": "abc"}]
        assert rejected == []
        assert manager._fake_client.store["user_library"][0]["device_id"] == "tablet"

    async def test_tombstone_kazanir(self):
        """Silme kaydı daha yeni HLC ile gelirse tombstone uygulanır."""
        manager = make_manager({})
        await manager.push_library("user-a", [make_record("abc", 1000)])
        await manager.push_library(
            "user-a", [make_record("abc", 2000, is_deleted=True, device="tablet")]
        )
        row = manager._fake_client.store["user_library"][0]
        assert row["is_deleted"] is True

    async def test_iki_cihaz_yarişi_deterministik(self):
        """
        Aynı HLC'ye sahip iki cihaz yarışır → cihaz kimliği kararı sabitler.

        Leksikografik olarak büyük cihaz kazanır ve bu, geliş sırasından
        BAĞIMSIZTIR: her iki sırada da kazanan aynı cihazdır. İki cihaz da aynı
        sonuca varır.
        """
        telefon = make_record("abc", 1000, 3, device="aaa-telefon")
        tablet = make_record("abc", 1000, 3, device="zzz-tablet")

        # Sıra 1: telefon önce gelir → tablet kazanır.
        manager = make_manager({})
        await manager.push_library("user-a", [telefon])
        applied, rejected = await manager.push_library("user-a", [tablet])
        assert applied == [{"item_type": "favorite", "content_id": "abc"}]
        assert rejected == []

        # Sıra 2: tablet önce gelir → telefon reddedilir, sunucu sürümü gelir.
        manager2 = make_manager({})
        await manager2.push_library("user-a", [tablet])
        applied2, rejected2 = await manager2.push_library("user-a", [telefon])
        assert applied2 == []
        assert rejected2[0]["reason"] == "server_newer"
        assert rejected2[0]["server_version"]["device_id"] == "zzz-tablet"

    async def test_karis_kaydi_yazilmaz(self):
        """Kaybeden cihazın verisi sunucuda EZİLMEZ."""
        manager = make_manager({})
        await manager.push_library("user-a", [make_record("abc", 5000, title="Kazanan")])
        await manager.push_library("user-a", [make_record("abc", 1000, title="Kaybeden")])
        row = manager._fake_client.store["user_library"][0]
        assert row["payload"] == {"title": "Kazanan"}

    async def test_farkli_kullaniciya_etki_etmez(self):
        """🔴 KRİTİK: A'nın kaydı B'nin tablosuna sızmaz."""
        manager = make_manager({})
        await manager.push_library("user-a", [make_record("abc", 1000)])
        applied, rejected = await manager.push_library(
            "user-b", [make_record("abc", 1000)]
        )
        assert applied == [{"item_type": "favorite", "content_id": "abc"}]
        assert rejected == []
        rows = manager._fake_client.store["user_library"]
        assert len(rows) == 2
        assert {row["user_id"] for row in rows} == {"user-a", "user-b"}


# ══════════════════════════════════════════════════════════════════════════════
# 3. BELGE BAZLI KOŞULLU UPSERT
# ══════════════════════════════════════════════════════════════════════════════


def make_document(doc_type, wall, counter=0, device="telefon", payload=None):
    return DocumentIn(
        doc_type=doc_type,
        payload=payload if payload is not None else {"seekDuration": 15},
        hlc=HlcStamp(wall=wall, counter=counter),
        device_id=device,
        client_updated_at=utc_now_iso(),
    )


@pytest.mark.asyncio
class TestPushDocuments:
    """POST /api/sync/push — belge bazlı LWW."""

    async def test_ilk_push_uygular(self):
        manager = make_manager({})
        applied, rejected = await manager.push_documents(
            "user-a", [make_document("player_settings", 1000)]
        )
        assert applied == ["player_settings"]
        assert rejected == []

    async def test_tekrar_push_rejected(self):
        manager = make_manager({})
        document = make_document("player_settings", 1000)
        await manager.push_documents("user-a", [document])
        applied, rejected = await manager.push_documents("user-a", [document])
        assert applied == []
        assert rejected[0]["doc_type"] == "player_settings"
        assert rejected[0]["reason"] == "server_equal"
        assert rejected[0]["server_version"]["payload"] == {"seekDuration": 15}

    async def test_daha_yeni_belge_uygular(self):
        manager = make_manager({})
        await manager.push_documents(
            "user-a", [make_document("player_settings", 1000, payload={"autoPlay": True})]
        )
        applied, _ = await manager.push_documents(
            "user-a", [make_document("player_settings", 2000, payload={"autoPlay": False})]
        )
        assert applied == ["player_settings"]
        assert manager._fake_client.store["user_documents"][0]["payload"] == {"autoPlay": False}

    async def test_kullanici_izolasyonu(self):
        manager = make_manager({})
        await manager.push_documents("user-a", [make_document("theme", 1000)])
        applied, rejected = await manager.push_documents("user-b", [make_document("theme", 1000)])
        assert applied == ["theme"] and rejected == []
        assert len(manager._fake_client.store["user_documents"]) == 2


# ══════════════════════════════════════════════════════════════════════════════
# 4. DELTA ÇEKME
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestPullDelta:
    """GET /api/sync/pull — `since` yalnızca değişen kayıtları döner."""

    async def test_since_oncesi_tam_dokum(self):
        manager = make_manager({})
        await manager.push_library(
            "user-a",
            [make_record("a", 1000), make_record("b", 1000), make_record("c", 1000)],
        )
        rows, has_more = await manager.fetch_library("user-a")
        assert {row["content_id"] for row in rows} == {"a", "b", "c"}
        assert has_more is False

    async def test_since_ile_delta(self):
        manager = make_manager({})
        await manager.push_library(
            "user-a", [make_record("a", 1000), make_record("b", 1000)]
        )
        checkpoint = fake_checkpoint()

        # Checkpoint'tan sonra YALNIZCA "a" değişir.
        await manager.push_library("user-a", [make_record("a", 2000)])

        rows, _ = await manager.fetch_library("user-a", since=checkpoint)
        assert {row["content_id"] for row in rows} == {"a"}

    async def test_since_ile_hicbir_degisiklik_yok(self):
        manager = make_manager({})
        await manager.push_library("user-a", [make_record("a", 1000)])
        checkpoint = fake_checkpoint()
        rows, _ = await manager.fetch_library("user-a", since=checkpoint)
        assert rows == []

    async def test_tombstone_delta_ile_de_gelir(self):
        """Silme bilgisi yalnızca tombstone satırının updated_at'ı ilerlediğinde gelir."""
        manager = make_manager({})
        await manager.push_library("user-a", [make_record("a", 1000)])
        checkpoint = fake_checkpoint()
        await manager.push_library(
            "user-a", [make_record("a", 2000, is_deleted=True, device="tablet")]
        )
        rows, _ = await manager.fetch_library("user-a", since=checkpoint)
        assert len(rows) == 1
        assert rows[0]["is_deleted"] is True

    async def test_has_more_sayfalamasi(self):
        manager = make_manager({})
        await manager.push_library(
            "user-a", [make_record(f"i{i}", 1000) for i in range(5)]
        )
        rows, has_more = await manager.fetch_library("user-a", limit=3)
        assert len(rows) == 3
        assert has_more is True

    async def test_tombstone_pull_donusu(self):
        """Silme bilgisi ancak tombstone satırıyla diğer cihaza ulaşabilir."""
        manager = make_manager({})
        await manager.push_library("user-a", [make_record("a", 1000)])
        await manager.push_library(
            "user-a", [make_record("a", 2000, is_deleted=True, device="tablet")]
        )
        rows, _ = await manager.fetch_library("user-a")
        assert len(rows) == 1
        assert rows[0]["is_deleted"] is True

    async def test_baska_kullanici_verisi_gorunmez(self):
        """🔴 KRİTİK: pull yalnızca kendi kullanıcının verisini döner."""
        manager = make_manager({})
        await manager.push_library("user-a", [make_record("gizli", 1000)])
        rows, _ = await manager.fetch_library("user-b")
        assert rows == []


# ══════════════════════════════════════════════════════════════════════════════
# 5. CİHAZ ENVANTERİ
# ══════════════════════════════════════════════════════════════════════════════


def make_device(device_id, name="Salon TV", platform="android"):
    return DeviceInfo(device_id=device_id, device_name=name, platform=platform,
                      app_version="1.0.0")


@pytest.mark.asyncio
class TestDeviceInventory:
    """user_devices — bağlı cihaz listesi ve iptal."""

    async def test_cihaz_kaydedilir_ve_isaretlenir(self):
        manager = make_manager({})
        await manager.touch_device("user-a", make_device("tv-1"))
        devices = await manager.list_devices("user-a")
        assert len(devices) == 1
        assert devices[0]["device_id"] == "tv-1"
        assert devices[0]["is_current"] is True

    async def test_yeni_cihaz_eskiyi_isaret_kaldirir(self):
        manager = make_manager({})
        await manager.touch_device("user-a", make_device("tv-1"))
        await manager.touch_device("user-a", make_device("telefon-1", platform="ios"))
        devices = {d["device_id"]: d for d in await manager.list_devices("user-a")}
        assert devices["telefon-1"]["is_current"] is True
        assert devices["tv-1"]["is_current"] is False

    async def test_ayni_cihaz_tekrar_kaydedilmez(self):
        manager = make_manager({})
        await manager.touch_device("user-a", make_device("tv-1"))
        await manager.touch_device("user-a", make_device("tv-1"))
        assert len(await manager.list_devices("user-a")) == 1

    async def test_iptal_listeden_duser(self):
        manager = make_manager({})
        await manager.touch_device("user-a", make_device("tv-1"))
        assert await manager.revoke_device("user-a", "tv-1") is True
        assert await manager.list_devices("user-a") == []

    async def test_iptal_bulunmayan_cihazda_false(self):
        manager = make_manager({})
        assert await manager.revoke_device("user-a", "yok") is False

    async def test_iptal_sonrasi_push_geri_cağırmaz(self):
        """İptal edilen cihaz push ederek kendini yeniden ekleyemez."""
        manager = make_manager({})
        await manager.touch_device("user-a", make_device("tv-1"))
        await manager.revoke_device("user-a", "tv-1")
        await manager.touch_device("user-a", make_device("tv-1"))
        assert await manager.list_devices("user-a") == []

    async def test_kullanici_izolasyonu(self):
        manager = make_manager({})
        await manager.touch_device("user-a", make_device("tv-1"))
        await manager.touch_device("user-b", make_device("tv-2"))
        assert [d["device_id"] for d in await manager.list_devices("user-a")] == ["tv-1"]
        # B, A'nın cihazını iptal edemez.
        assert await manager.revoke_device("user-b", "tv-1") is False


# ══════════════════════════════════════════════════════════════════════════════
# 6. ŞEMA SÖZLEŞMESİ — DDL ile kodun uyumu
# ══════════════════════════════════════════════════════════════════════════════


def _ddl_columns(table):
    """`schema_sync.sql` içinden bir tablonun kolon adlarını çıkarır."""
    import re

    sql = (ROOT_DIR / "supabase" / "schema_sync.sql").read_text(encoding="utf-8")
    match = re.search(
        rf"CREATE TABLE IF NOT EXISTS {table} \((.*?)\n\);", sql, re.S
    )
    assert match, f"{table} tablosu DDL'de bulunamadı"
    block = match.group(1)
    columns = set()
    for line in block.splitlines():
        line = line.split("--")[0].strip()
        if not line or line.upper().startswith(("CONSTRAINT", "CHECK", "UNIQUE")):
            continue
        columns.add(line.split()[0])
    return columns


def _written_columns():
    """
    Kodun GERÇEKTEN yazdığı kolonlar.

    Okuma sabitlerini (`_X_COLUMNS`) yeniden kullanmak yanıltıcı olurdu:
    `user_id` hiçbir SELECT listesinde görünmez ama tüm yazma yollarının
    kullanıcı izolasyon anahtarıdır. Burada satır üreticileri doğrudan çağrılır.
    """
    record = SyncRecordIn(
        item_type="favorite",
        content_id="a",
        hlc=HlcStamp(wall=1, counter=0),
        device_id="d",
    )
    document = DocumentIn(doc_type="theme", hlc=HlcStamp(wall=1, counter=0), device_id="d")
    device = DeviceInfo(device_id="d", device_name="TV", platform="android")

    return {
        "user_library": set(_library_row("u", record)) | {"user_id"},
        "user_documents": set(_document_row("u", document)) | {"user_id"},
        "user_devices": {
            "user_id", "device_id", "device_name", "platform",
            "app_version", "is_current", "last_pushed_at",
        } | set(device.model_dump()),
    }


class TestSchemaContract:
    """
    Kodun okuduğu/yazdığı her kolon DDL'de VAR OLMALI.

    Sahte istemci eksik kolonları sessizce düşürdüğü için bu test gereklidir:
    `is_deleted` kolonu DDL'den unutulduğunda tüm belge senkronizasyonu gerçek
    veritabanında 500 döner ama sahte testler yeşil kalır.
    """

    @pytest.mark.parametrize(
        "table,columns",
        [
            ("user_library", _LIBRARY_COLUMNS),
            ("user_documents", _DOCUMENT_COLUMNS),
            ("user_devices", _DEVICE_COLUMNS),
        ],
    )
    def test_okunan_kolonlar_ddlde_var(self, table, columns):
        ddl = _ddl_columns(table)
        for column in columns.split(","):
            column = column.strip()
            assert column in ddl, f"{table}.{column} DDL'de tanımlı değil"

    @pytest.mark.parametrize("table", ["user_library", "user_documents", "user_devices"])
    def test_yazilan_kolonlar_ddlde_var(self, table):
        """Satır üreticilerinin yazdığı kolonlar DDL'de tanımlı olmalı."""
        ddl = _ddl_columns(table)
        for column in sorted(_written_columns()[table]):
            assert column in ddl, f"{table}.{column} yazılıyor ama DDL'de yok"

    @pytest.mark.parametrize(
        "table,key",
        [
            # user_profiles birincil anahtar olarak `id` kullanır (auth.users.id).
            ("user_profiles", "id"),
            ("user_documents", "user_id"),
            ("user_library", "user_id"),
            ("user_devices", "user_id"),
        ],
    )
    def test_kullanici_izolasyon_anahtari_var(self, table, key):
        """
        Kullanıcı izolasyon anahtarı hiçbir tabloda eksik olamaz.

        Bu kolonların var olmaması tüm testleri yeşil bırakırken üretimde her
        sorguyu tüm kullanıcılara açık hale getirirdi.
        """
        assert key in _ddl_columns(table)

    def test_profil_kolonlari_ddlde_var(self):
        ddl = _ddl_columns("user_profiles")
        for column in (
            "id", "username", "display_name", "avatar_url", "bio",
            "language", "birth_date", "is_private", "created_at", "updated_at",
        ):
            assert column in ddl, f"user_profiles.{column} DDL'de tanımlı değil"

    def test_item_type_check_kosulu_ile_uyumlu(self):
        import re

        sql = (ROOT_DIR / "supabase" / "schema_sync.sql").read_text(encoding="utf-8")
        block = re.search(
            r"CREATE TABLE IF NOT EXISTS user_library \((.*?)\n\);", sql, re.S
        ).group(1)
        allowed = set(re.findall(r"'([a-z_]+)'", block))
        assert allowed == set(LIBRARY_ITEM_TYPES)

    def test_on_conflict_hedefleri_unique_kisitlariyla_uyumlu(self):
        """Her `on_conflict` değeri DDL'deki UNIQUE kısıtının kolonlarıyla birebir aynıdır."""
        import re

        sql = (ROOT_DIR / "supabase" / "schema_sync.sql").read_text(encoding="utf-8")
        unique = {
            name: tuple(column.strip() for column in columns.split(","))
            for name, columns in re.findall(
                r"CONSTRAINT (\w+) UNIQUE \(([^)]+)\)", sql
            )
        }
        assert unique["unique_user_item"] == ("user_id", "item_type", "content_id")
        assert unique["unique_user_document"] == ("user_id", "doc_type")
        assert unique["unique_user_device"] == ("user_id", "device_id")


# ══════════════════════════════════════════════════════════════════════════════
# 7. MODEL DOĞRULAMA
# ══════════════════════════════════════════════════════════════════════════════


class TestSyncModels:
    def test_gecersiz_item_type_reddedilir(self):
        with pytest.raises(Exception):
            SyncRecordIn(
                item_type="bilinmeyen",
                content_id="a",
                hlc=HlcStamp(wall=1, counter=0),
                device_id="x",
            )

    def test_content_id_sayisal_olabilir(self):
        record = SyncRecordIn(
            item_type="favorite",
            content_id=550,
            hlc=HlcStamp(wall=1, counter=0),
            device_id="x",
        )
        assert record.content_id == "550"

    def test_bos_cihaz_kimligi_reddedilir(self):
        with pytest.raises(Exception):
            SyncRecordIn(
                item_type="favorite",
                content_id="a",
                hlc=HlcStamp(wall=1, counter=0),
                device_id="   ",
            )

    def test_row_to_stamp_bozuk_satiri_toleranse_edir(self):
        assert row_to_stamp({}).wall == 0
        assert row_to_stamp({"hlc_wall": 5, "hlc_counter": 2}).counter == 2
