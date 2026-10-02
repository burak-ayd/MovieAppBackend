# Oluşturan: Burak Aydoğan
#
# Akış: oynatıcı sayfasındaki video kimliği -> POST /player/index.php
#       -> JSON `securedLink` (m3u8)

import re
from typing import Any, List, Optional

from Core.Extractor.ExtractorBase import ExtractorBase
from Core.Extractor.ExtractorModels import ExtractResult


class HDPlayerSystem(ExtractorBase):
    name     = "HDPlayerSystem"
    main_url = "https://hdplayersystem.com"

    def can_handle_url(self, url: str) -> bool:
        return bool(url) and "hdplayersystem.com" in url

    async def extract(self, url: str, referer: Optional[str] = None, **kwargs: Any):
        referer = referer or f"{self.main_url}/"

        # video/{hash} ya da ?data={hash}
        vid_id = url.split("video/")[1] if "video/" in url else url.split("?data=")[1]
        vid_id = vid_id.split("/")[0].split("&")[0]

        yanit = await self.httpx.post(
            f"{self.main_url}/player/index.php?data={vid_id}&do=getVideo",
            data={"hash": vid_id, "r": referer},
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": referer,
            },
            timeout=30.0,
        )

        try:
            veri = yanit.json()
        except Exception as e:
            raise ValueError(f"{self.name}: yanıt JSON değil ({e})") from e

        m3u8 = veri.get("securedLink") or veri.get("videoSource")
        if not m3u8:
            raise ValueError(f"{self.name}: m3u bağlantısı bulunamadı")

        return ExtractResult(
            name=self.name,
            url=self.fix_url(m3u8.replace(".txt", ".m3u8") if m3u8.endswith(".txt") else m3u8),
            referer=url,
            headers={"Referer": url},
        )


HDPlayerSystemExtractor = HDPlayerSystem