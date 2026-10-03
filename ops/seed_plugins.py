#!/usr/bin/env python3
"""
Plugins volume senkronizasyonu — imajdaki (seed) kodu `Plugins/` volume'una yazar.

Neden var?
----------
`/app/Plugins` bir **named volume**. Docker, volume'u mount ederken imajın
üzerine yazar; yani container içindeki `/app/Plugins` **her zaman volume'daki
(eski) kod** görünür. Entrypoint'in eski mantığı yalnızca volume'da OLMAYAN
dosyaları kopyalıyordu:

    if [ ! -e "$target" ]; then cp "$file" "$target"; fi

Sonuç: Bir eklenti dosyası bir kez volume'a girdiyse, **sonraki tüm deploy'lar
ona dokunmuyor**. Yani plugin kodunda yapılan HER değişiklik (poster @2x
seçimi, yeni alan, hata düzeltmesi) sessizce yok sayılır ve API eski kodla
çalışır. Belirti: loglarda sürüm yeni ("1.2.0") ama davranış eski.

Ne korunur?
-----------
`Core/Helpers/Kontrol.py` çalışma sırasında plugin dosyalarını düzenler; fakat
YALNIZCA `main_url = "..."` satırını değiştirir (satır bazında `str.replace`).
Bu yüzden tek istisna o değerdir: volume'daki güncel `main_url` seed kopyasına
geri yazılır, kalan kod imajdaki güncel hâliyle gelir.

    seed:   main_url = "https://yeni.example"  + yeni kod
    volume: main_url = "https://guncel.example" + eski kod
    sonuç:  main_url = "https://guncel.example" + yeni kod   ✅

Güvenlik
--------
* Yazma atomiktir (geçici dosya + `os.replace`) → yarım dosya kalmaz.
* İki konteyner (api + domain-updater) aynı anda çalışabilir; `flock` ile ilki
  senkronize eder, diğeri atlar (ikisi de aynı seed'i yazdığı için sonuç aynı).
* Volume'da seed'de OLMAYAN dosyalar SİLİNMEZ, yalnızca raporlanır.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# Core/Helpers/Kontrol.py ve ops/domain_watcher.py ile BİREBİR aynı desen.
MAIN_URL_RE = re.compile(r'(main_url\s*=\s*)(["\'])(https?://.*?)(\2)')

try:  # Windows'ta (yerel testler) fcntl yok; kilit opsiyoneldir.
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


def log(message: str) -> None:
    # Kapsayıcıda UTF-8 sorun değil; ancak Windows konsol codepage'i (cp1254)
    # Unicode okları basamaz ve UnicodeEncodeError entrypoint'i öldürürdü.
    metin = f"[seed] {message}"
    try:
        print(metin, flush=True)
    except UnicodeEncodeError:
        print(metin.encode("ascii", "replace").decode("ascii"), flush=True)


def main_url_de(icerik: str) -> str | None:
    """Dosya metnindeki `main_url` değeri (yoksa None)."""
    eslesme = MAIN_URL_RE.search(icerik)
    return eslesme.group(3) if eslesme else None


def main_url_yaz(icerik: str, url: str) -> str | None:
    """`main_url` satırını verilen URL ile değiştirir (desen yoksa None)."""
    if not MAIN_URL_RE.search(icerik):
        return None
    return MAIN_URL_RE.sub(
        lambda m: f"{m.group(1)}{m.group(2)}{url}{m.group(4)}", icerik, count=1
    )


def atomik_yaz(hedef: Path, icerik: bytes) -> None:
    """Geçici dosya + replace: yarım yazılmış plugin dosyası bırakmaz."""
    gecici = hedef.with_name(f".{hedef.name}.seed-tmp")
    gecici.write_bytes(icerik)
    os.replace(gecici, hedef)


def _kilit_al(kilit_dosyasi: Path | None):
    """`flock` ile çapraz-konteyner kilidi. Kullanılamazsa None döner."""
    if fcntl is None or kilit_dosyasi is None:
        return None
    try:
        kilit_dosyasi.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(kilit_dosyasi), os.O_CREAT | os.O_RDWR, 0o644)
    except OSError as e:
        log(f"UYARI: kilit açılamadı ({e}); kilitsiz devam ediliyor.")
        return None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        log("Başka bir konteyner senkronize ediyor; atlandı.")
        return False
    return fd


def _kilit_birak(fd) -> None:
    if not fd:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def yazilabilir_mi(dizin: Path) -> bool:
    """Dizin gerçekten yazılabilir mi? (Sahiplik sessizce bozuk olabilir.)"""
    try:
        dene = dizin / ".seed-yazma-denemesi"
        dene.write_text("ok", encoding="utf-8")
        dene.unlink()
        return True
    except OSError:
        return False


def senkronize(seed_dir: Path, hedef_dir: Path) -> dict[str, int]:
    """Seed → hedef senkronizasyonu. Sayısal özet döndürür."""
    # `__init__.py` de dahil: plugin listesini taşıdığı için KOD'dur. Kontrol.py
    # onun içeriğini değiştirmediğinden üzerine yazmak güvenlidir.
    seed_dosyalar = sorted(p for p in seed_dir.glob("*.py") if p.is_file())
    if not seed_dosyalar:
        log(f"UYARI: {seed_dir} içinde plugin dosyası yok.")
        return {"yeni": 0, "guncellenen": 0, "ayni": 0, "korunan": 0}

    yeni = guncellenen = ayni = korunan = 0

    for seed_dosya in seed_dosyalar:
        hedef = hedef_dir / seed_dosya.name
        seed_icerik = seed_dosya.read_bytes()

        if not hedef.exists():
            atomik_yaz(hedef, seed_icerik)
            yeni += 1
            log(f"+ {seed_dosya.name}: yeni eklenti eklendi.")
            continue

        hedef_icerik = hedef.read_bytes()
        if hedef_icerik == seed_icerik:
            ayni += 1
            continue

        # Kod farklı → volume kopyası eski olabilir. Güncellenmiş main_url'i koru.
        seed_icerik_str = seed_icerik.decode("utf-8")
        seed_url = main_url_de(seed_icerik_str)
        try:
            volume_url = main_url_de(hedef_icerik.decode("utf-8"))
        except UnicodeDecodeError:
            volume_url = None

        korunacak = bool(volume_url and volume_url != seed_url)
        if korunacak:
            seed_icerik_str = main_url_yaz(seed_icerik_str, volume_url) or seed_icerik_str

        # ⚠️ `main_url` korunduğu için içerik seed ile bayt bayt aynı olmayabilir.
        #    Gerçek ölçüt "hedefe göre değişti mi" — aksi halde her açılışta aynı
        #    dosya 'güncellendi' diye sayılır ve gereksiz yazılır (log yanıltır).
        hedef_icerik_yeni = seed_icerik_str.encode("utf-8")
        if hedef_icerik_yeni == hedef_icerik:
            ayni += 1
            continue

        atomik_yaz(hedef, hedef_icerik_yeni)
        guncellenen += 1

        if korunacak:
            korunan += 1
            log(f"↻ {seed_dosya.name}: yeni kod uygulandı, main_url korundu ({volume_url}).")
        else:
            log(f"↻ {seed_dosya.name}: yeni kod uygulandı.")

    fazlalar = sorted(
        p.name
        for p in hedef_dir.glob("*.py")
        if p.is_file()
        and not p.name.startswith("__")
        and not (seed_dir / p.name).exists()
    )
    if fazlalar:
        log(
            f"UYARI: seed'de olmayan {len(fazlalar)} dosya volume'da duruyor (silinmedi): "
            + ", ".join(fazlalar[:5])
            + (" ..." if len(fazlalar) > 5 else "")
        )

    toplam = len([p for p in hedef_dir.glob("*.py") if p.is_file()])
    log(
        f"Plugins: {toplam} eklenti | yeni {yeni} | güncellenen {guncellenen} | "
        f"ayni {ayni} | korunan main_url {korunan}"
    )
    return {"yeni": yeni, "guncellenen": guncellenen, "ayni": ayni, "korunan": korunan}


def main() -> int:
    parser = argparse.ArgumentParser(description="Plugins volume'unu seed ile eşitler")
    parser.add_argument("--seed", default=os.getenv("SEED_DIR", "/app/.seed") + "/Plugins")
    parser.add_argument("--target", default="/app/Plugins")
    parser.add_argument("--lock", default=os.getenv("STATE_DIR", "/state") + "/seed.lock")
    args = parser.parse_args()

    seed_dir, hedef_dir = Path(args.seed), Path(args.target)

    if not seed_dir.is_dir():
        log(f"HATA: seed dizini yok: {seed_dir}")
        return 1

    try:
        hedef_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        log(f"HATA: {hedef_dir} oluşturulamadı: {e}")
        return 1

    # Yazılamıyorsa eski kodla sessizce çalışmaktansa açıkça başarısız ol.
    if not yazilabilir_mi(hedef_dir):
        log(
            f"HATA: {hedef_dir} yazılabilir değil. Sahiplik bozuk; "
            f"'docker compose run --rm api chown -R app:app {hedef_dir}' deneyin."
        )
        return 1

    fd = _kilit_al(Path(args.lock))
    if fd is False:          # başka konteyner senkronize ediyor
        return 0
    try:
        senkronize(seed_dir, hedef_dir)
    finally:
        _kilit_birak(fd)

    return 0


if __name__ == "__main__":
    sys.exit(main())