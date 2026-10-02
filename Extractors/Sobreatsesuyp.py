# Oluşturan: Burak Aydoğan
#
# TRsTX ile aynı aile: `file":"..."` -> POST /<file> -> JSON liste
#                        -> POST /playlist/<file[1:]>.txt -> m3u8 metni

import re
from typing import Any, List, Optional, Union

from Core.Extractor.ExtractorBase import ExtractorBase
from Core.Extractor.ExtractorModels import ExtractResult


class Sobreatsesuyp(ExtractorBase):
    name     = "Sobreatsesuyp"
    main_url = "https://sobreatsesuyp.com"

    def can_handle_url(self, url: str) -> bool:
        return bool(url) and "sobreatsesuyp" in url

    async def extract(self, url: str, referer: Optional[str] = None, **kwargs: Any):
        referer = referer or self.main_url
        basliklar = {"Referer": referer, "X-Requested-With": "XMLHttpRequest"}

        istek = await self.httpx.get(url, headers=basliklar)
        istek.raise_for_status()

        m = re.search(r'file":"([^"]+)', istek.text)
        if not m:
            raise ValueError(f"{self.name}: 'file' alanı bulunamadı ({url})")

        liste_url = f"{self.main_url}/{m.group(1).replace(chr(92), '')}"
        yanit = await self.httpx.post(liste_url, headers=basliklar)
        if "application/json" not in (yanit.headers.get("content-type") or ""):
            yanit = await self.httpx.get(liste_url, headers=basliklar)

        try:
            ham = yanit.json()
        except Exception as e:
            raise ValueError(f"{self.name}: liste JSON'u okunamadı ({e})") from e

        if not isinstance(ham, list):
            raise ValueError(f"{self.name}: beklenen liste değil: {type(ham).__name__}")

        sonuclar: List[ExtractResult] = []
        for kalem in ham[1:]:
            if not isinstance(kalem, dict):
                continue
            baslik = kalem.get("title")
            dosya = kalem.get("file")
            if not baslik or not dosya or not isinstance(dosya, str):
                continue

            ham_yol = dosya[1:] if dosya.startswith("/") else dosya.lstrip("/")
            video = await self.httpx.post(f"{self.main_url}/playlist/{ham_yol}.txt", headers=basliklar)
            m3u8 = video.text.strip()
            if not m3u8.startswith("http"):
                continue

            sonuclar.append(ExtractResult(
                name    = f"{self.name} - {baslik}",
                url     = m3u8,
                referer = referer,
                headers = {"Referer": referer},
            ))

        if not sonuclar:
            raise ValueError(f"{self.name}: oynatılabilir kaynak bulunamadı ({url})")

        return sonuclar[0] if len(sonuclar) == 1 else sonuclar


SobreatsesuypExtractor = Sobreatsesuyp