"""FilmMakinesi oynatıcıları için ortak çözümleme tabanı.

Kotlin kaynak: Kekik-cloudstream/FilmMakinesi
  - CloseLoadExtractor.kt -> https://closeload.filmmakinesi.to
  - RapidExtractor.kt     -> https://rapid.filmmakinesi.to

İki oynatıcı da aynı şifreleme ailesini kullanıyor (paketlenmiş JS -> `dc_...`
değiştirici -> XOR/Caesar karışımı). Mevcut `resolve_player_stream` bu
zinciri çözebildiği için her iki extractor da onu kullanıyor; yalnızca
altyazı ve `Origin` başlıkları farklılaşıyor.
"""

import json
import re

from typing import Any, Dict, List, Optional

from Core.Extractor.ExtractorBase import ExtractorBase
from Core.Extractor.ExtractorModels import ExtractResult, Subtitle
from Core.Extractor.DecoderHelpers import JsUnpacker, resolve_player_stream
from Core.Helpers import debug_log


class FilmMakinesiBase(ExtractorBase):
    """Ortak altyapı: sayfa çekme, akış çözümleme ve altyazı ayrıştırma."""

    # Altyazı etiketlerini Türkçeye çeviren eşleme
    _DIL_ESLESME = (
        (("turkish", "turkce", "turkçe", "\"tr\""), "Türkçe"),
        (("forced",), "Forced"),
        (("english", "eng", "ingilizce", "\"en\""), "İngilizce"),
    )

    def __init__(self):
        super().__init__()

    def get_source_label(self, url: str) -> str:
        return self.name

    def _get_headers(self, referer: Optional[str]) -> Dict[str, str]:
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Referer": referer or self.main_url,
            "Accept": "*/*",
        }

    async def _fetch_page(self, url: str, referer: Optional[str]) -> str:
        """Oynatıcı sayfasını çeker. httpx -> cloudscraper -> curl_cffi sırası."""
        import asyncio

        headers = self._get_headers(referer)
        text = ""

        try:
            cevap = await self.client.get(url, headers=headers, follow_redirects=True)
            text = cevap.text or ""
            debug_log(f"[{self.name}] httpx HTTP={cevap.status_code} len={len(text)}")
        except Exception as e:
            debug_log(f"[{self.name}] httpx exception: {e!r}")

        if text and len(text) > 500:
            return text

        loop = asyncio.get_event_loop()
        try:
            cs_text = await loop.run_in_executor(
                None,
                lambda: self.cloudscraper.get(url, headers=headers, timeout=20).text,
            )
            debug_log(f"[{self.name}] cloudscraper len={len(cs_text or '')}")
            if cs_text and len(cs_text) > 500:
                return cs_text
            text = text or cs_text
        except Exception as e:
            debug_log(f"[{self.name}] cloudscraper exception: {e!r}")

        try:
            from curl_cffi.requests import Session as CffiSession

            def _cffi():
                with CffiSession(impersonate="chrome120") as s:
                    s.headers.update(headers)
                    return s.get(url, timeout=20, allow_redirects=True).text

            cffi_text = await loop.run_in_executor(None, _cffi)
            debug_log(f"[{self.name}] curl_cffi len={len(cffi_text or '')}")
            if cffi_text and len(cffi_text) > 500:
                return cffi_text
        except Exception as e:
            debug_log(f"[{self.name}] curl_cffi exception: {e!r}")

        return text

    @staticmethod
    def _temizle(deger: str) -> str:
        return (deger or "").replace(r"\/", "/").replace('\\"', '"').replace("\\", "")

    def _altyazi_etiket(self, etiket: str, dil_kodu: str = "") -> Optional[str]:
        """`label` / `language` alanından Türkçe etiket üretir."""
        birlesik = f"{etiket} {dil_kodu}".lower()
        for desenler, ad in self._DIL_ESLESME:
            if any(d in birlesik for d in desenler):
                return ad
        return None

    def _altyazilari_coz(self, html: str) -> List[Subtitle]:
        """`tracks: [...]` (JWPlayer) ve `<track src=...>` (HTML5) biçimlerini okur."""
        altyazilar: List[Subtitle] = []
        gorulen = set()

        # --- 1) JWPlayer `tracks: [{"file": ..., "label": ..., "language": ...}]` ---
        blok = re.search(r"tracks\s*:\s*(\[.*?\])", html, re.DOTALL)
        if blok:
            try:
                kayitlar = json.loads(blok.group(1))
            except (ValueError, TypeError):
                kayitlar = []
                for satir in re.finditer(
                    r'"file"\s*:\s*"([^"]+)"(?:.*?)"label"\s*:\s*"([^"]*)"'
                    r'(?:.*?)"language"\s*:\s*"([^"]*)"', blok.group(1), re.DOTALL
                ):
                    kayitlar.append({"file": satir.group(1),
                                     "label": satir.group(2),
                                     "language": satir.group(3)})

            for kayit in kayitlar:
                if not isinstance(kayit, dict):
                    continue
                dosya = self._temizle(str(kayit.get("file") or ""))
                if not dosya:
                    continue
                ad = self._altyazi_etiket(str(kayit.get("label") or ""),
                                          str(kayit.get("language") or ""))
                if not ad:
                    continue
                adres = self._mutlak_adres(dosya)
                if adres in gorulen:
                    continue
                gorulen.add(adres)
                altyazilar.append(Subtitle(name=ad, url=adres))

        # --- 2) HTML5 `<track>` etiketleri ---
        for etiket in re.finditer(
            r'<track[^>]*?\ssrc\s*=\s*["\']([^"\']+)["\'][^>]*>', html, re.IGNORECASE
        ):
            dosya = self._temizle(etiket.group(1))
            if not dosya:
                continue
            blok_attr = etiket.group(0)
            ad = self._altyazi_etiket(
                (re.search(r'label\s*=\s*["\']([^"\']*)["\']', blok_attr, re.I) or
                 re.search(r'srclang\s*=\s*["\']([^"\']*)["\']', blok_attr, re.I)
                 ).group(1) if (
                    re.search(r'label\s*=\s*["\']([^"\']*)["\']', blok_attr, re.I)
                    or re.search(r'srclang\s*=\s*["\']([^"\']*)["\']', blok_attr, re.I)
                ) else ""
            )
            if not ad:
                continue
            adres = self._mutlak_adres(dosya)
            if adres in gorulen:
                continue
            gorulen.add(adres)
            altyazilar.append(Subtitle(name=ad, url=adres))

        return altyazilar

    def _mutlak_adres(self, dosya: str) -> str:
        """Göreli altyazı yollarını oynatıcı kök adresine tamamlar."""
        if dosya.startswith("http://") or dosya.startswith("https://"):
            return dosya
        return f"{self.main_url.rstrip('/')}/{dosya.lstrip('/')}"

    async def _akisi_dogrula(self, akis_url: str, referer: str) -> bool:
        """Master playlist gerçekten servis ediliyor mu diye kontrol eder."""
        try:
            cevap = await self.client.get(
                akis_url,
                headers={
                    "User-Agent": self._get_headers(None)["User-Agent"],
                    "Referer": referer,
                    "Accept": "*/*",
                    "Origin": self.main_url.rstrip("/"),
                },
            )
            if cevap.status_code != 200:
                debug_log(f"[{self.name}] master HTTP {cevap.status_code}: {akis_url[:90]}")
                return False
            return "#EXTM3U" in (cevap.text or "")
        except Exception as e:
            debug_log(f"[{self.name}] master kontrol hatası: {e!r}")
            return False

    def _cozumle(self, html: str) -> Optional[str]:
        """Paketlenmiş JS'i açar ve oynatıcı akış adresini döndürür."""
        # 1) Doğrudan çözümleyici (paketlenmiş kodu da açabilir)
        akis = resolve_player_stream(html)
        if akis:
            return self._temizle(akis)

        # 2) Packer'ı elle aç, sonra yeniden dene
        if "eval(function(p,a,c,k,e" in html:
            try:
                acilan = JsUnpacker.unpack(html)
                if acilan:
                    akis = resolve_player_stream(acilan)
                    if akis:
                        return self._temizle(akis)
            except Exception as e:
                debug_log(f"[{self.name}] JsUnpacker hatası: {e!r}")

        # 3) JSON-LD contentUrl (Kotlin'deki yedek yol)
        m = re.search(r'"contentUrl"\s*:\s*"([^"]+)"', html)
        if m:
            return self._temizle(m.group(1)).replace(".txt", ".m3u8")

        # 4) Düz m3u8
        m = re.search(r'(https?://[^"\'\s]+\.m3u8[^"\'\s]*)', html)
        if m:
            return self._temizle(m.group(1))

        return None

    async def extract(
        self, url: str, referer: Optional[str] = None, **kwargs: Any
    ) -> Optional[ExtractResult]:
        base_referer = referer or self.main_url
        html = await self._fetch_page(url, base_referer)

        if not html or len(html) < 200:
            print(f"[!] {self.name}: oynatıcı sayfası okunamadı ({url})")
            return None

        akis_url = self._cozumle(html)
        if not akis_url:
            print(f"[!] {self.name}: video adresi çözülemedi ({url})")
            return None

        # Master doğrulanamıyorsa yine de döndür (API katmanı denesin)
        await self._akisi_dogrula(akis_url, url)

        altyazilar = self._altyazilari_coz(html)

        return ExtractResult(
            name=self.name,
            url=akis_url,
            referer=url,
            headers={
                "User-Agent": self._get_headers(None)["User-Agent"],
                "Referer": url,
                "Accept": "*/*",
                "Origin": self.main_url.rstrip("/"),
            },
            subtitles=altyazilar,
        )

