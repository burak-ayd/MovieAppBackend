# Bu araç @keyiflerolsun tarafından | @KekikAkademi için yazılmıştır.
# Python portu: Kekik-cloudstream / TurboImgzExtractor.kt
#
# FullHDFilmizlesene bu adrese "anahtar||adres" biçiminde verir; çıkarıcı
# anahtarı ayırmak için url.split("||")[-1] kullanır (Kotlin: substringAfter("||")).

import re
from typing import Any, Optional, Union

from Core.Extractor.ExtractorBase import ExtractorBase
from Core.Extractor.ExtractorModels import ExtractResult


class TurboImgz(ExtractorBase):
    name     = "TurboImgz"
    main_url = "https://turbo.imgz.me"

    def can_handle_url(self, url: str) -> bool:
        return bool(url) and ("turbo.imgz.me" in url or "imgz.me" in url)

    async def extract(self, url: str, referer: Optional[str] = None, **kwargs: Any):
        referer = referer or self.main_url

        # "atom||https://..." -> "https://..."
        hedef = url.split("||")[-1].strip()
        anahtar = url.split("||")[0].upper() if "||" in url else self.name.upper()

        istek = await self.httpx.get(hedef, headers={"Referer": referer})
        istek.raise_for_status()

        m = re.search(r'file:\s*"(.*?)"', istek.text)
        if not m:
            raise ValueError(f"{self.name}: 'file' alanı bulunamadı ({hedef})")

        return ExtractResult(
            name    = f"{self.name} - {anahtar}",
            url     = m.group(1).strip(),
            referer = referer,
            headers = {"Referer": referer},
        )


TurboImgzExtractor = TurboImgz