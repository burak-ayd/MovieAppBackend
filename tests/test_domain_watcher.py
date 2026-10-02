"""
`ops/domain_watcher.py` zamanlama mantığı testleri.

Domain kontrolü günde iki slotta yapılır (sabah PROBE, akşam UPDATE). Bu testler
`next_event` / `slot_listesi` hesabını geçmiş, gelecek ve sınır durumlar için
doğrular. Ağ çağrısı yapılmaz.
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

try:  # domain_watcher dosya kilidi için `fcntl` kullanıyor (Unix/konteyner).
    import fcntl  # noqa: F401
except ImportError:
    pytest.skip("domain_watcher fcntl gerektiriyor (Unix konteyner)", allow_module_level=True)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ops import domain_watcher as dw  # noqa: E402


def _slotlari_yukle(probe=(9, 0), update=(18, 0)):
    """Test için saatleri geçici olarak değiştirir, sonra eski haline döndürür."""
    eski = (dw.PROBE_HOUR, dw.PROBE_MINUTE, dw.UPDATE_HOUR, dw.UPDATE_MINUTE)
    dw.PROBE_HOUR, dw.PROBE_MINUTE = probe
    dw.UPDATE_HOUR, dw.UPDATE_MINUTE = update
    return eski


@pytest.fixture
def slotlar():
    """Varsayılan 09:00 / 18:00 slotlarıyla çalışan testler için."""
    eski = _slotlari_yukle()
    yield
    dw.PROBE_HOUR, dw.PROBE_MINUTE, dw.UPDATE_HOUR, dw.UPDATE_MINUTE = eski


def test_slot_listesi_iki_soket_dondurur(slotlar):
    assert dw.slot_listesi() == [(9, 0), (18, 0)]


def test_slot_listesi_ayni_saatleri_tekillestirir():
    eski = _slotlari_yukle(probe=(18, 0), update=(18, 0))
    try:
        assert dw.slot_listesi() == [(18, 0)]
    finally:
        dw.PROBE_HOUR, dw.PROBE_MINUTE, dw.UPDATE_HOUR, dw.UPDATE_MINUTE = eski


def test_sabah_oncesi_sonraki_slot_sabah(slotlar):
    now = datetime(2026, 10, 3, 6, 30)
    hedef, etiket = dw.next_event(now)
    assert etiket == (9, 0)
    assert hedef == datetime(2026, 10, 3, 9, 0)


def test_sabah_ve_ak_sam_arasinda_sonraki_slot_aksam(slotlar):
    now = datetime(2026, 10, 3, 14, 15)
    hedef, etiket = dw.next_event(now)
    assert etiket == (18, 0)
    assert hedef == datetime(2026, 10, 3, 18, 0)


def test_aksam_sonrasi_yarina_sabaha_atlar(slotlar):
    now = datetime(2026, 10, 3, 21, 5)
    hedef, etiket = dw.next_event(now)
    assert etiket == (9, 0)
    assert hedef == datetime(2026, 10, 4, 9, 0)


def test_slot_aninda_slot_gecmis_sayilir(slotlar):
    """Tam slot anında tekrar tetiklenmemeli; bir sonraki slota geçilmeli."""
    now = datetime(2026, 10, 3, 9, 0)
    hedef, etiket = dw.next_event(now)
    assert etiket == (18, 0)
    assert hedef == datetime(2026, 10, 3, 18, 0)


def test_slot_saniyesi_gecmis_sayilir(slotlar):
    """Slot geçtikten 1 saniye sonra da aynı gün içinde yeniden seçilmez."""
    now = datetime(2026, 10, 3, 9, 0, 1)
    _, etiket = dw.next_event(now)
    assert etiket == (18, 0)


def test_gun_l_sinirlarinda_sonraki_slot(slotlar):
    """23:59'da bir sonraki kontrol ertesi gün 09:00 olmalı."""
    now = datetime(2026, 10, 3, 23, 59, 59)
    hedef, etiket = dw.next_event(now)
    assert etiket == (9, 0)
    assert hedef - now <= timedelta(days=1)


def test_ozel_slotlarla_sabah_erken(slotlar):
    eski = _slotlari_yukle(probe=(6, 30), update=(20, 15))
    try:
        now = datetime(2026, 10, 3, 7, 0)
        hedef, etiket = dw.next_event(now)
        assert etiket == (20, 15)
        assert hedef == datetime(2026, 10, 3, 20, 15)
    finally:
        dw.PROBE_HOUR, dw.PROBE_MINUTE, dw.UPDATE_HOUR, dw.UPDATE_MINUTE = eski


def test_yapilandirilabilir_slotlar_env_ile(monkeypatch):
    """PROBE_HOUR / UPDATE_HOUR ortam değişkenleri saatleri belirler."""
    eski = (dw.PROBE_HOUR, dw.PROBE_MINUTE, dw.UPDATE_HOUR, dw.UPDATE_MINUTE)
    try:
        monkeypatch.setenv("PROBE_HOUR", "7")
        monkeypatch.setenv("PROBE_MINUTE", "45")
        monkeypatch.setenv("UPDATE_HOUR", "21")
        monkeypatch.setenv("UPDATE_MINUTE", "5")
        assert dw._env_slot("PROBE_HOUR", "PROBE_MINUTE", (9, 0)) == (7, 45)
        assert dw._env_slot("UPDATE_HOUR", "UPDATE_MINUTE", (18, 0)) == (21, 5)
    finally:
        dw.PROBE_HOUR, dw.PROBE_MINUTE, dw.UPDATE_HOUR, dw.UPDATE_MINUTE = eski


@pytest.mark.parametrize(
    "hour, minute, fallback",
    [("abc", "0", (9, 0)), ("25", "0", (9, 0)), ("9", "99", (9, 0)), ("", "", (9, 0)), (None, None, (9, 0))],
)
def test_gecersiz_slot_degerleri_varsayilana_duser(hour, minute, fallback):
    assert dw._env_slot("H", "M", fallback) == fallback


def test_env_int_sinirlari(monkeypatch):
    monkeypatch.setenv("X", "42")
    assert dw._env_int("X", 60, 10, 150) == 42
    assert dw._env_int("X", 60, 50) == 50         # alt sınıra kırpılır
    assert dw._env_int("X", 60, None, 30) == 30   # üst sınıra kırpılır

    monkeypatch.setenv("X", "bozuk")
    assert dw._env_int("X", 60, 10, 150) == 60    # varsayılana düşer

    monkeypatch.setenv("X", "")
    assert dw._env_int("X", 60, 10, 150) == 60    # boş → varsayılan


def test_kalp_atisi_saglik_kontrolunden_kisa_kalir():
    """healthcheck 180s sınırı: bekleme aralığı ondan küçük olmalı."""
    assert dw.HEARTBEAT_INTERVAL < 180


def test_uyari_listesi_uygulama_basinda_bos():
    """Varsayılan ortamda (DOMAIN_CHECK_INTERVAL yok) uyarı üretilmemeli."""
    if not os.getenv("DOMAIN_CHECK_INTERVAL"):
        assert not [u for u in dw._uyarilar if "DOMAIN_CHECK_INTERVAL" in u]