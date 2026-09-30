# Bu araç @keyiflerolsun tarafından | @KekikAkademi için yazılmıştır.
# Python portu: Kekik-cloudstream / RapidVidExtractor.kt
#
# İki nesil oynatıcı desteklenir:
#   1) Yeni (2026): sayfadaki `window._p8='...'` → base64( ters ) → "K9L" kaydırması
#      → base64 → JSON. Kaynak `cm` (HLS) / `tm` (MP4), altyazı `ct`.
#      (Algoritma core.min.js içinde birebir aynıdır.)
#   2) Eski: `jwSetup.sources` → `av('...')` → aynı şifreleme.
#
# Not: canlı alan adı `rapidvid.org`; Kotlin'te `rapidvid.net` yazıyordu.
# İkisi de kabul edilir (can_handle_url her ikisini de tanır).

import base64
import json
import re
from typing import Any, List, Optional, Union

from Core.Extractor.ExtractorBase import ExtractorBase
from Core.Extractor.ExtractorModels import ExtractResult, Subtitle


class RapidVid(ExtractorBase):
    name     = "RapidVid"
    main_url = "https://rapidvid.net"

    # canlı kullanılan alan adı
    ALAN_ADLARI = ("rapidvid.org", "rapidvid.net", "rapidvid.cc", "rapidvid.to")

    ANAHTAR = "K9L"

    def can_handle_url(self, url: str) -> bool:
        if not url:
            return False
        return any(alan in url for alan in self.ALAN_ADLARI)

    # ------------------------------------------------------------------ #
    # Şifreleme (Kotlin decodeSecret / core.min.js)
    # ------------------------------------------------------------------ #

    def _b64(self, veri: str) -> bytes:
        """Base64 çözme; JS `atob` gibi boşluk/tamamlama toleranslı."""
        temiz = veri.strip().replace("\n", "").replace("\r", "")
        dolgu = "=" * (-len(temiz.rstrip("=")) % 4)
        try:
            return base64.b64decode(temiz + dolgu)
        except Exception:
            return b""

    def decode_secret(self, kod: str) -> str:
        """Geri alınan base64 → 'K9L' kaydırması → base64."""
        if not kod:
            return ""

        ilk = self._b64(kod[::-1])
        if not ilk:
            return ""

        cikti = bytearray()
        for i, bayt in enumerate(ilk):
            kaydirma = ord(self.ANAHTAR[i % len(self.ANAHTAR)]) % 5 + 1
            cikti.append((bayt - kaydirma) & 0xFF)

        return self._b64(cikti.decode("latin-1")).decode("utf-8", "replace")

    # ------------------------------------------------------------------ #
    # Yardımcılar
    # ------------------------------------------------------------------ #

    @staticmethod
    def _etiket_duzelt(etiket: str) -> str:
        return (etiket or "").replace("\\u0131", "ı").replace("\\u0130", "İ") \
                           .replace("\\u00fc", "ü").replace("\\u00e7", "ç").strip()

    # ------------------------------------------------------------------ #
    # Yeni oynatıcı: window._p8
    # ------------------------------------------------------------------ #

    def _p8_coz(self, html: str) -> Optional[dict]:
        m = re.search(r"window\._p8\s*=\s*'([^']+)'", html)
        if not m:
            return None
        try:
            veri = json.loads(self.decode_secret(m.group(1)))
            return veri if isinstance(veri, dict) else None
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    # Eski oynatıcı: jwSetup
    # ------------------------------------------------------------------ #

    def _jw_setup_coz(self, html: str) -> tuple:
        """(altyazilar, m3u8 veya None)"""
        altyazilar: List[Subtitle] = []
        script = next((s for s in re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)
                       if "jwSetup.sources" in s), "")
        if not script:
            return altyazilar, None

        m = re.search(r"jwSetup\.tracks\s*=\s*(\[.*?\])\s*;", script, re.S)
        if m:
            try:
                for parca in json.loads(m.group(1)):
                    if isinstance(parca, dict) and parca.get("label"):
                        altyazilar.append(Subtitle(
                            name = self._etiket_duzelt(parca["label"]),
                            url  = str(parca.get("file", "")).replace("\\", ""),
                        ))
            except Exception:
                pass

        m = re.search(r"jwSetup\.sources\s*=\s*(.*?);", script, re.S)
        av = re.search(r"av\('([^']+)'\)", m.group(1)) if m else None
        if not av:
            return altyazilar, None

        return altyazilar, self.decode_secret(av.group(1))

    # ------------------------------------------------------------------ #
    # Ana giriş noktası
    # ------------------------------------------------------------------ #

    async def extract(self, url: str, referer: Optional[str] = None, **kwargs: Any):
        # TurboImgz benzeri "anahtar||adres" biçimi gelebilir
        if "||" in url:
            url = url.split("||")[-1]

        referer = referer or self.main_url
        istek = await self.httpx.get(url, headers={"Referer": referer})
        istek.raise_for_status()
        html = istek.text

        # --- yeni nesil ---
        veri = self._p8_coz(html)
        if veri:
            kaynak = veri.get("cm") or veri.get("tm") or ""
            if kaynak:
                altyazilar = []
                for parca in (veri.get("ct") or []):
                    if isinstance(parca, dict) and parca.get("label"):
                        altyazilar.append(Subtitle(
                            name = self._etiket_duzelt(parca["label"]),
                            url  = str(parca.get("file", "")).replace("\\", ""),
                        ))

                return ExtractResult(
                    name      = self.name,
                    url       = kaynak,
                    referer   = referer,
                    headers   = {"Referer": referer},
                    subtitles = altyazilar,
                )

        # --- eski nesil ---
        altyazilar, m3u8 = self._jw_setup_coz(html)
        if m3u8:
            return ExtractResult(
                name      = self.name,
                url       = m3u8,
                referer   = referer,
                headers   = {"Referer": referer},
                subtitles = altyazilar,
            )

        raise ValueError(f"{self.name}: oynatıcı verisi bulunamadı ({url})")


RapidVidExtractor = RapidVid