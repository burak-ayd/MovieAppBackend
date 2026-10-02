# Oluşturan: Burak Aydoğan
# ! https://github.com/recloudstream/cloudstream/blob/master/library/src/commonMain/kotlin/com/lagradost/cloudstream3/extractors/Vidmoly.kt

import asyncio
import contextlib
import json
import re
import sys
from pathlib import Path

from Core.Extractor import ExtractorBase, ExtractResult, Subtitle


class VidMoly(ExtractorBase):
    name     = "VidMoly"
    main_url = "https://vidmoly.net"

    async def extract(self, url: str, referer: str = None) -> ExtractResult:
        if referer:
            self.httpx.headers.update({"Referer": referer})

        self.httpx.headers.update({
            "User-Agent"     : "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Sec-Fetch-Dest" : "iframe",
        })

        if self.main_url.endswith(".me"):
            self.main_url = self.main_url.replace(".me", ".net")
            url           = url.replace(".me", ".net")

        # Embed URL oluştur
        embed_url      = url.replace("/w/", "/embed-") + "-920x360.html" if "/w/" in url else url
        script_content = None
        attempts       = 0

        # Script verisini almak için deneme yap
        while attempts < 10 and not script_content:
            attempts += 1
            response = await self.httpx.get(embed_url)
            # save response.html to a file for debugging
            with open("response.html", "w", encoding="utf-8") as f:
                f.write(response.text)
            response.raise_for_status()

            script_match   = re.search(r"sources:\s*\[(.*?)\],", response.text, re.DOTALL)

            script_content = script_match[1] if script_match else None
            if not script_content:
                await asyncio.sleep(0.5)

        if not script_content:
            raise ValueError("Gerekli script bulunamadı.")

        # Video kaynaklarını ayrıştır
        video_data = self._add_marks(script_content, "file")
        # video_data = { "file": 'https://box-1094-q.vmeas.cloud/hls/xqx2ojhqdrokjiqbtfpslo2fufyq7tqoulpqpkh6b,xnzczmvfswecuooqrxq,7nzczmvfswltzzmj3ya,.urlset/master.m3u8' }
        try:
            video_sources = json.loads(f"[{video_data.replace("'", '\"')}]")
        except json.JSONDecodeError as hata:
            raise ValueError("Video kaynakları ayrıştırılamadı.") from hata

        # Altyazı kaynaklarını ayrıştır
        subtitles = []
        if subtitle_match := re.search(r"tracks:\s*\[(.*?)\]", response.text, re.DOTALL):
            subtitle_data = self._add_marks(subtitle_match[1], "file")
            subtitle_data = self._add_marks(subtitle_data, "label")
            subtitle_data = self._add_marks(subtitle_data, "kind")

            with contextlib.suppress(json.JSONDecodeError):
                subtitle_sources = json.loads(f"[{subtitle_data}]")
                subtitles = [
                    Subtitle(
                        name = sub.get("label"),
                        url  = self.fix_url(sub.get("file")),
                    )
                        for sub in subtitle_sources
                            if sub.get("kind") == "captions"
                ]
        # İlk video kaynağını al
        video_url = None
        for source in video_sources:
            if file_url := source.get("file"):
                video_url = file_url
                break

        if not video_url:
            raise ValueError("Video URL bulunamadı.")

        await self.close()
        return ExtractResult(
            name      = self.name,
            url       = video_url,
            referer   = self.main_url,
            headers   = {},
            subtitles = subtitles
        )

    def _add_marks(self, text: str, field: str) -> str:
        """
        Verilen alanı çift tırnak içine alır.
        """
        return re.sub(rf"\"?{field}\"?", f"\"{field}\"", text)