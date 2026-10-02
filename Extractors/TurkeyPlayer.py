# Oluşturan: Burak Aydoğan
#
# Sayfadaki `var video = {...};` bloğundan id + md5 alınır ve master playlist
# URL'si üretilir.

import json
import re
from typing import Any, Optional, Union

from Core.Extractor.ExtractorBase import ExtractorBase
from Core.Extractor.ExtractorModels import ExtractResult


class TurkeyPlayer(ExtractorBase):
    name     = "TurkeyPlayer"
    main_url = "https://watch.turkeyplayer.com/"

    def can_handle_url(self, url: str) -> bool:
        return bool(url) and "turkeyplayer.com" in url

    async def extract(self, url: str, referer: Optional[str] = None, **kwargs: Any):
        referer = referer or self.main_url

        istek = await self.httpx.get(url, headers={"Referer": referer})
        istek.raise_for_status()

        m = re.search(r"var\s+video\s*=\s*(\{.*?\});", istek.text, re.S)
        if not m:
            raise ValueError(f"{self.name}: 'var video' JSON'u bulunamadı ({url})")

        try:
            veri = json.loads(m.group(1))
            video_id = veri["id"]
            md5 = veri["md5"]
        except Exception as e:
            raise ValueError(f"{self.name}: video verisi okunamadı ({e})") from e

        master = (f"{self.main_url}m3u8/8/{md5}/master.txt"
                  f"?s=1&id={video_id}&cache=1")

        return ExtractResult(
            name    = self.name,
            url     = master,
            referer = referer,
            headers = {"Referer": referer},
        )


TurkeyPlayerExtractor = TurkeyPlayer