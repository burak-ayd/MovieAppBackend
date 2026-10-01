# Bu araç @keyiflerolsun tarafından | @KekikAkademi için yazılmıştır.
# Python portu: Kekik-cloudstream / VideoSeyredExtractor.kt
#
# Akış: embed/{id} -> GET /playlist/{id}.json -> sources[].file + tracks[]

from typing import Any, List, Optional, Union

from Core.Extractor.ExtractorBase import ExtractorBase
from Core.Extractor.ExtractorModels import ExtractResult, Subtitle


class VideoSeyred(ExtractorBase):
    name     = "VideoSeyred"
    main_url = "https://videoseyred.in"

    def can_handle_url(self, url: str) -> bool:
        return bool(url) and "videoseyred" in url

    async def extract(self, url: str, referer: Optional[str] = None, **kwargs: Any):
        referer = referer or f"{self.main_url}/"
        video_id = url.split("embed/")[-1].split("?")[0].split("/")[0]
        if not video_id:
            raise ValueError(f"{self.name}: video kimliği çıkarılamadı ({url})")

        yanit = await self.httpx.get(f"{self.main_url}/playlist/{video_id}.json", timeout=30.0)

        try:
            liste = yanit.json()
        except Exception as e:
            raise ValueError(f"{self.name}: playlist JSON değil ({e})") from e

        if isinstance(liste, dict):
            liste = [liste]
        if not liste:
            raise ValueError(f"{self.name}: playlist boş ({video_id})")

        kayit = liste[0]

        altyazilar: List[Subtitle] = []
        for track in (kayit.get("tracks") or []):
            if track.get("kind") == "captions" and track.get("label"):
                altyazilar.append(Subtitle(
                    name=track["label"],
                    url=self.fix_url(track.get("file") or ""),
                ))

        sonuclar: List[ExtractResult] = []
        for source in (kayit.get("sources") or []):
            dosya = source.get("file")
            if not dosya:
                continue
            sonuclar.append(ExtractResult(
                name=f"{self.name} - {source.get('title') or 'Auto'}",
                url=self.fix_url(dosya),
                referer=referer,
                headers={"Referer": f"{self.main_url}/"},
                subtitles=altyazilar,
            ))

        if not sonuclar:
            raise ValueError(f"{self.name}: kaynak bulunamadı ({video_id})")

        return sonuclar[0] if len(sonuclar) == 1 else sonuclar


VideoSeyredExtractor = VideoSeyred