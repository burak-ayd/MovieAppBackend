"""
`ops/seed_plugins.py` testleri — Plugins volume senkronizasyonu.

Kritik kural: seed'deki **yeni kod** uygulanır, volume'daki güncellenmiş
`main_url` **korunur** ve işlem **idempotenttir** (her açılışta aynı dosya
"güncellendi" diye sayılmaz).
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ops.seed_plugins import main_url_de, main_url_yaz, senkronize  # noqa: E402

PLUGIN = (
    "class X:\n"
    '    name = "X"\n'
    '    main_url = "{0}"\n'
    "    # {1}\n"
    '    SURUM = "{2}"\n'
)


def _yaz(dizin: Path, ad: str, domain: str, yorum: str, surum: str) -> None:
    # NOT: `not` Python anahtar sözcüğü olduğu için konumlu geçirilir.
    (dizin / ad).write_text(PLUGIN.format(domain, yorum, surum), encoding="utf-8")


@pytest.fixture
def seed_hedef(tmp_path):
    seed, hedef = tmp_path / "seed", tmp_path / "hedef"
    seed.mkdir()
    hedef.mkdir()
    return seed, hedef


def test_yeni_eklenti_kopyalanir(seed_hedef):
    seed, hedef = seed_hedef
    _yaz(seed, "A.py", "https://repo.example", "yeni", "v1")

    ozet = senkronize(seed, hedef)
    assert ozet["yeni"] == 1
    assert "v1" in (hedef / "A.py").read_text(encoding="utf-8")


def test_yeni_kod_uygulanir_ve_main_url_korunur(seed_hedef):
    """Kullanıcının yaşadığı asıl senaryo: volume eski kod, seed yeni kod."""
    seed, hedef = seed_hedef

    # Volume: eski kod + Kontrol.py'nin güncellediği domain
    _yaz(hedef, "A.py", "https://guncel.example", "eski", "v1")
    # Seed: yeni kod + repodaki varsayılan domain
    _yaz(seed, "A.py", "https://repo.example", "yeni", "v2")

    ozet = senkronize(seed, hedef)
    sonuc = (hedef / "A.py").read_text(encoding="utf-8")

    assert ozet["guncellenen"] == 1 and ozet["korunan"] == 1
    assert "v2" in sonuc, "yeni kod uygulanmadı"
    assert "eski" not in sonuc, "eski kod kaldı"
    assert main_url_de(sonuc) == "https://guncel.example", "main_url korunmadı"


def test_islem_idempotent(seed_hedef):
    seed, hedef = seed_hedef
    _yaz(hedef, "A.py", "https://guncel.example", "eski", "v1")
    _yaz(seed, "A.py", "https://repo.example", "yeni", "v2")

    senkronize(seed, hedef)
    ilk = (hedef / "A.py").read_bytes()

    ozet = senkronize(seed, hedef)
    assert ozet == {"yeni": 0, "guncellenen": 0, "ayni": 1, "korunan": 0}, ozet
    assert (hedef / "A.py").read_bytes() == ilk, "dosya tekrar yazıldı"


def test_ayni_dosyaya_dokunulmaz(seed_hedef):
    seed, hedef = seed_hedef
    _yaz(seed, "A.py", "https://repo.example", "not", "v1")
    _yaz(hedef, "A.py", "https://repo.example", "not", "v1")

    ozet = senkronize(seed, hedef)
    assert ozet["ayni"] == 1 and ozet["guncellenen"] == 0


def test_seedde_olmayan_dosya_silinmez(seed_hedef):
    """Kullanıcının domain'i volume'da; repo'dan kaldırılmış olabilir."""
    seed, hedef = seed_hedef
    _yaz(seed, "A.py", "https://repo.example", "not", "v1")
    _yaz(hedef, "Eski.py", "https://eski.example", "not", "v1")

    senkronize(seed, hedef)
    assert (hedef / "Eski.py").exists(), "seed'de olmayan dosya silinmemeli"


def test_init_py_de_kod_olarak_tazelenir(seed_hedef):
    """
    `Plugins/__init__.py` plugin listesini içerir; yeni eklenti eklendiğinde
    bu dosya da güncellenmelidir. Kontrol.py yalnızca `main_url` değiştirdiği
    için üzerine yazmak güvenlidir.
    """
    seed, hedef = seed_hedef
    (seed / "__init__.py").write_text("from .A import A\n", encoding="utf-8")
    (seed / "A.py").write_text("class A: pass\n", encoding="utf-8")
    (hedef / "__init__.py").write_text("# eski liste\n", encoding="utf-8")

    senkronize(seed, hedef)
    assert (hedef / "__init__.py").read_text(encoding="utf-8") == "from .A import A\n"


def test_main_url_yazma_tirnak_ve_hizalamayi_korur():
    icerik = 'class A:\n    main_url = "https://eski.example"\n    x = 1\n'
    yeni = main_url_yaz(icerik, "https://yeni.example")
    assert main_url_de(yeni) == "https://yeni.example"
    assert 'main_url = "https://yeni.example"' in yeni, "tırnak/hizalama korunmalı"
    assert '    x = 1\n' in yeni, "dosyanın geri kalanı bozulmamalı"


def test_main_url_deseni_kontrol_ile_ayni():
    """Kontrol.py'nin deseniyle aynı olmalı; aksi halde domain bozulur."""
    from Core.Helpers.Kontrol import MainUrlGuncelleyici

    icerik = 'class A:\n    main_url = "https://eski.example"\n'
    kontrol = MainUrlGuncelleyici()
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as dosya:
        dosya.write(icerik)
        yol = dosya.name

    try:
        assert kontrol._main_url_bul(yol)[2] == main_url_de(icerik)
    finally:
        Path(yol).unlink(missing_ok=True)


def test_cli_calisir_ve_kilit_dosyasi_kullanir(tmp_path):
    """Gerçek çalıştırma: yazılabilirlik kontrolü + flock yolu da sınanır."""
    seed, hedef = tmp_path / "seed", tmp_path / "hedef"
    seed.mkdir()
    hedef.mkdir()
    _yaz(seed, "A.py", "https://repo.example", "not", "v1")

    cikti = subprocess.run(
        [
            sys.executable, str(ROOT / "ops" / "seed_plugins.py"),
            "--seed", str(seed),
            "--target", str(hedef),
            "--lock", str(tmp_path / "seed.lock"),
        ],
        capture_output=True,
        text=True,
    )
    assert cikti.returncode == 0, cikti.stderr
    assert (hedef / "A.py").exists()
    assert "[seed]" in cikti.stdout


def test_cli_hedef_yazilabilir_degilse_basarisiz(tmp_path):
    """Eski kodla sessizce çalışmaktense açık hata vermeli."""
    seed = tmp_path / "seed"
    seed.mkdir()
    _yaz(seed, "A.py", "https://repo.example", "not", "v1")

    cikti = subprocess.run(
        [
            sys.executable, str(ROOT / "ops" / "seed_plugins.py"),
            "--seed", str(seed),
            "--target", str(tmp_path / "yok" / "Plugins"),
            "--lock", str(tmp_path / "seed.lock"),
        ],
        capture_output=True,
        text=True,
    )
    assert cikti.returncode == 0, "dizin yoksa oluşturulmalı"

    seed_yok = subprocess.run(
        [
            sys.executable, str(ROOT / "ops" / "seed_plugins.py"),
            "--seed", str(tmp_path / "olmayan"),
            "--target", str(tmp_path / "Plugins"),
        ],
        capture_output=True,
        text=True,
    )
    assert seed_yok.returncode == 1, "seed yoksa hata dönmeli"