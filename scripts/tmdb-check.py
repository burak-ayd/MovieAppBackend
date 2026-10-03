#!/usr/bin/env python3
"""
TMDB anahtarı teşhis aracı.

Kullanım:
    python scripts/tmdb-check.py

Neden var? "Görseller gelmiyor / TMDB 401 dönüyor" sorusunun cevabı genelde
anahtardadır ve anahtarı loglara basmak **güvenlik riskidir**. Bu araç
anahtarı asla basmaz; yalnızca yapısını (uzunluk, biçim, JWT bölümleri) ve
gerçek API'ye olumlu/olumsuz cevabı gösterir.

Çıktı örneği:
    uzunluk        : 276
    nokta sayisi   : 2
    eyJ ile baslıyor: False        ← standart JWT değil / kopyalama bozuk
    [v4 Bearer] HTTP 200  sonuc: 3   ✅ çalışıyor
    [v3 api_key ] HTTP 401  Invalid API key  ← bu türden bir anahtar kullanmayın

Güvenlik: anahtarın kendisi hiçbir çıktıda yer almaz.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import sys
from pathlib import Path

try:
    import httpx
except ImportError:
    print("HATA: httpx yüklü değil. `pip install httpx`", file=sys.stderr)
    raise SystemExit(1)

ROOT = Path(__file__).resolve().parents[1]
ENV_DOSYASI = ROOT / ".env"
V3_DESEN = re.compile(r"^[0-9a-f]{32}$", re.IGNORECASE)
ANAHTAR_KELEP = re.compile(r"(?m)^\s*TMDB_API_KEY\s*=\s*(.*)$")


def _guvenli(metin: str) -> None:
    try:
        print(metin)
    except UnicodeEncodeError:
        print(metin.encode("ascii", "replace").decode("ascii"))


def env_dosyasindan() -> tuple[str | None, str]:
    """(.env içindeki ham değer, kaynak açıklaması)"""
    if not ENV_DOSYASI.exists():
        return None, ".env yok"
    m = ANAHTAR_KELEP.search(ENV_DOSYASI.read_text(encoding="utf-8"))
    if not m:
        return None, ".env içinde TMDB_API_KEY satırı yok"
    return m.group(1), ".env"


def degeri_temizle(ham: str) -> str:
    return (ham or "").strip().strip('"').strip("'")


def tur_tahmin(deger: str) -> str:
    if not deger:
        return "bilinmiyor"
    if V3_DESEN.match(deger):
        return "v3"
    if deger.count(".") == 2 and len(deger) > 100:
        return "v4"
    return "bilinmiyor"


def jwt_bolumlerini_coz(deger: str) -> None:
    """JWT başlığı/payload'ını gösterir (imza ASLA basılmaz)."""
    parcalar = deger.split(".")
    if len(parcalar) != 3:
        return
    for ad, parca in (("baslik", parcalar[0]), ("payload", parcalar[1])):
        try:
            yama = parca + "=" * (-len(parca) % 4)
            metin = base64.urlsafe_b64decode(yama).decode("utf-8", "replace")
        except Exception:
            _guvenli(f"  JWT {ad:8}: ÇÖZÜLEMEDİ (muhtemelen bozuk kopyalanmış)")
            continue
        if ad == "payload":
            # Kimlik bilgisi alanlarını gizle
            metin = re.sub(r'"(sub|aud|jti)":"[^"]*"', r'"\1":"<gizli>"', metin)
        _guvenli(f"  JWT {ad:8}: {metin[:170]}")


def _tek_deneme(istemci, etiket: str, url: str, *, params=None, headers=None) -> tuple[int, str]:
    """Tek istek; ağ hatası dahil HİÇBİR koşulda traceback bırakmaz."""
    try:
        yanit = istemci.get(url, params=params, headers=headers)
    except httpx.TimeoutException:
        return 0, "zaman aşımı — TMDB'ye ulaşılamıyor (ağ/internet sorunu)"
    except httpx.ConnectError as e:
        return 0, f"bağlantı hatası: {type(e).__name__} (ağ engeli/proxy olabilir)"
    except Exception as e:  # pragma: no cover
        return 0, f"beklenmeyen hata: {type(e).__name__}: {e}"

    if yanit.status_code == 200:
        return 200, ""
    return yanit.status_code, _mesaj(yanit)


def api_denemesi(deger: str) -> int:
    """Her iki yöntemle dener; çalışan yöntemi döndürür (0 = hiçbiri)."""
    base = "https://api.themoviedb.org/3"
    with httpx.Client(timeout=20.0) as istemci:
        kod, hata = _tek_deneme(
            istemci, "v3", f"{base}/search/multi",
            params={"api_key": deger, "query": "matrix", "language": "tr-TR"},
        )
        print(f"[v3  ?api_key=]  HTTP {kod or '—'}")
        if hata:
            _guvenli(f"                {hata}")

        kod, hata = _tek_deneme(
            istemci, "v4", f"{base}/search/multi",
            headers={"Authorization": f"Bearer {deger}"},
            params={"query": "matrix", "language": "tr-TR"},
        )
        print(f"[v4  Bearer]     HTTP {kod or '—'}")

        if kod == 200:
            try:
                sayi = len((istemci.get(f"{base}/search/multi",
                                        headers={"Authorization": f"Bearer {deger}"},
                                        params={"query": "matrix"}).json() or {}).get("results") or [])
            except Exception:
                sayi = 0
            _guvenli(f"                sonuç sayısı: {sayi}  ✅ ÇALIŞIYOR")
            return 1
        if hata:
            _guvenli(f"                {hata}")

        return 0


def _mesaj(yanit) -> str:
    try:
        return str((yanit.json() or {}).get("status_message") or "(mesaj yok)")[:120]
    except Exception:
        return "(yanıt okunamadı)"


def main() -> int:
    print("=" * 66)
    print("TMDB anahtarı teşhisi  (anahtarın kendisi ASLA basılmaz)")
    print("=" * 66)

    kaynak = "ortam değişkeni"
    deger = (os.environ.get("TMDB_API_KEY") or "").strip()
    ham_env = None
    if ENV_DOSYASI.exists():
        m = ANAHTAR_KELEP.search(ENV_DOSYASI.read_text(encoding="utf-8"))
        if m:
            ham_env = degeri_temizle(m.group(1))
            kaynak = ".env"

    if not deger and not ham_env:
        print("\nHATA: TMDB_API_KEY tanımlı değil.")
        print("      .env dosyasına ekleyin veya ortam değişkeni olarak tanımlayın.")
        return 1

    if deger and ham_env and deger != ham_env:
        _guvenli(
            "\nUYARI: ortam değişkeni ile .env içindeki değer FARKLI.\n"
            "       python-dotenv varsayılan olarak ortam değişkenini EZMEZ;\n"
            "       çalışan süreç .env'i değil ortam değişkenini kullanıyor olabilir."
        )

    deger = deger or (ham_env or "")
    print(f"\nKaynak             : {kaynak}")
    print(f"Uzunluk            : {len(deger)}")
    print(f"Nokta sayısı       : {deger.count('.')}")
    print(f"Boşluk içeriyor mu : {any(c.isspace() for c in deger)}")
    print(f"eyJ ile başlıyor   : {deger.startswith('eyJ')}")
    print(f"v3 biçimi (32 hex) : {bool(V3_DESEN.match(deger))}")
    print(f"Tur tahmini        : {tur_tahmin(deger)}")
    print(f"Kimlik (sha256/8)  : {hashlib.sha256(deger.encode()).hexdigest()[:8]}")
    if deger.count(".") == 2:
        jwt_bolumlerini_coz(deger)

    print("\n--- Gerçek API denemesi ---")
    calisiyor = api_denemesi(deger)

    print()
    if calisiyor:
        print("SONUÇ: Anahtar geçerli. Görsel zenginleştirme çalışmalı.")
        print("      Hâlâ görsel gelmiyorsa API loglarında '[tmdb]' satırlarına bakın.")
        return 0

    print("SONUÇ: Anahtar GEÇERSİZ — TMDB isteği 401 döndü.")
    print()
    print("  Düzeltme adımları:")
    print("   1. https://www.themoviedb.org/settings/api adresini açın")
    print("   2. 'API Key (v3 auth)' değerini kopyalayın (32 onaltılık karakter).")
    print("      Bu en sorunsuz yol: kısa olduğu için kopyalarken bozulmaz.")
    print("   3. .env içindeki TMDB_API_KEY satırını bu değerle değiştirin.")
    print("   4. API'yi yeniden başlatın.")
    print()
    print("  Not: 'API Read Access Token' (v4) ~1000 karakter uzunluğunda bir JWT'dir.")
    print("       Kısa kesildiyse/başında-sonunda fazladan karakter varsa 401 döner.")
    print("       Kopyalarken alanın tamamını seçtiğinizden emin olun.")
    return 1


if __name__ == "__main__":
    sys.exit(main())