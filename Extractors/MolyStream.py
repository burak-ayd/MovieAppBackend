# Bu araç @keyiflerolsun tarafından | @KekikAkademi için yazılmıştır.
from Core.Extractor import ExtractorBase, ExtractResult, Subtitle
from Core.Helpers import konsol, HTMLHelper



import re
from urllib.parse import urlparse, urljoin

class MolyStream(ExtractorBase):
    name     = "MolyStream"
    main_url = "https://dbx.molystream.org"

    # Birden fazla domain destekle
    supported_domains = [
        "dbx.molystream.org",
        "ydx.molystream.org",
        "yd.sheila.stream",
        "ydf.popcornvakti.net",
    ]

    def can_handle_url(self, url: str) -> bool:
        return any(domain in url for domain in self.supported_domains)

    async def extract(self, url, referer=None) -> ExtractResult:
        """
        MolyStream HLS akışını çıkar.

        MolyStream URL yapısı:
          - /embed/sheila/XXXX  → HLS master playlist (#EXTM3U, Content-Type: text/html)
          - /embed/XXXX/q/1     → HLS media playlist (segment listesi)

        Akış:
          1) URL'ye istek at
          2) İçerik M3U8 ise → master/media playlist olarak çözümle
          3) İçerik HTML ise → video#sheplayer source src veya file:'...' pattern'i bul
          4) Altyazıları (addSrtFile) tespit et
          5) Sonuçları ExtractResult olarak döndür
        """
        # MolyStream /q/1 linklerinde /embed/sheila/ varsa /embed/'e normalize et
        if "/q/" in url and "/embed/sheila/" in url:
            url = url.replace("/embed/sheila/", "/embed/")

        request_referer = referer or self.main_url
        request_headers = {
            "Referer"    : request_referer,
            "User-Agent" : "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }

        # Sayfayı çek (Cloudflare koruması için cloudscraper fallback)
        try:
            resp = await self.httpx.get(url, headers=request_headers, follow_redirects=True)
            content = resp.text
            if not content.strip().startswith("#EXTM3U") and not ("video#sheplayer" in content or "addSrtFile" in content):
                # Cloudflare challenge veya block durumunda cloudscraper ile dene
                scraper_resp = self.cloudscraper.get(url, headers=request_headers, timeout=20)
                if scraper_resp.status_code == 200:
                    content = scraper_resp.text
        except Exception:
            scraper_resp = self.cloudscraper.get(url, headers=request_headers, timeout=20)
            content = scraper_resp.text

        subtitles = []

        # İçerik M3U8 formatında mı kontrol et
        if content.strip().startswith("#EXTM3U"):
            # M3U8 içeriğini çözümle
            video, segment_referer = self._parse_m3u8(content, url)

            # Eğer master playlist ise ve media playlist URL'si bulunduysa
            # media playlist'i de çek ve segment referer'ı belirle
            if video != url:
                try:
                    resp2 = await self.httpx.get(video, headers={
                        "Referer"    : request_referer,
                        "User-Agent" : "Mozilla/5.0 (X11; Linux x86_64; rv:101.0) Gecko/20100101 Firefox/101.0",
                    }, follow_redirects=True)
                    content2 = resp2.text
                    if content2.strip().startswith("#EXTM3U"):
                        # Media playlist'ten segment domain'ini al
                        segment_referer = self._extract_segment_referer(content2)
                except Exception:
                    pass

            return ExtractResult(
                name       = self.name,
                url        = video,
                referer    = segment_referer,
                headers    = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:101.0) Gecko/20100101 Firefox/101.0"},
                subtitles  = subtitles
            )

        # İçerik HTML ise → video source veya file pattern'i bul
        secici = HTMLHelper(content)
        video  = secici.select_attr("video#sheplayer source", "src")

        if not video:
            # Fallback: file: '...' pattern
            video = secici.regex_first(r"""file:\s*['"]([^'"]+)['"]""")

        if not video:
            # Son çare: URL'nin kendisini kullan
            video = url

        # URL düzeltme
        video = self.fix_url(video)

        # Altyazıları çıkar (HTML sayfasından)
        matches = secici.regex_all(
            r"addSrtFile\(['\"]([^'\"]+\.srt)['\"]\s*,\s*['\"][a-z]{2}['\"]\s*,\s*['\"]([^'\"]+)['\"]"
        )
        subtitles = [
            Subtitle(name=name, url=self.fix_url(srt_url))
            for srt_url, name in matches
        ]

        # Eğer bulunan URL bir M3U8 ise, onu da çözümle
        resolved_url, resolved_referer = await self._resolve_hls(video, referer=request_referer)

        return ExtractResult(
            name       = self.name,
            url        = resolved_url,
            referer    = resolved_referer,
            headers    = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:101.0) Gecko/20100101 Firefox/101.0"},
            subtitles  = subtitles
        )

    def _parse_m3u8(self, content: str, base_url: str) -> tuple[str, str]:
        """
        M3U8 içeriğini parse eder.
        Master playlist ise → ilk stream URL'sini döndürür.
        Media playlist ise → base_url'i olduğu gibi döndürür.

        Returns:
            (stream_url, referer)
        """
        lines = content.split("\n")
        stream_url = None

        for i, line in enumerate(lines):
            line = line.strip()
            if line.startswith("#EXT-X-STREAM-INF") and i + 1 < len(lines):
                candidate = lines[i + 1].strip()
                if candidate and not candidate.startswith("#"):
                    if not candidate.startswith("http"):
                        candidate = urljoin(base_url, candidate)
                    stream_url = candidate

        if stream_url:
            # Master playlist → media playlist URL'si bulundu
            parsed = urlparse(stream_url)
            referer = f"{parsed.scheme}://{parsed.netloc}/"
            return stream_url, referer

        # Media playlist (segment listesi) — base_url'i döndür
        segment_referer = self._extract_segment_referer(content)
        return base_url, segment_referer

    def _extract_segment_referer(self, m3u8_content: str) -> str:
        """
        Media playlist içeriğinden segment URL'lerinin domain'ini çıkarır.
        Bu domain, segment isteklerinde Referer olarak kullanılır.
        """
        for line in m3u8_content.split("\n"):
            line = line.strip()
            if line.startswith("http") and not line.startswith("#"):
                parsed = urlparse(line)
                return f"{parsed.scheme}://{parsed.netloc}/"

        return self.main_url

    async def _resolve_hls(self, stream_url: str, referer: str) -> tuple[str, str]:
        """
        Eğer URL bir HLS master playlist ise → media playlist URL'sini çözer.
        Değilse → olduğu gibi döndürür.

        Returns:
            (media_playlist_url, referer_for_segments)
        """
        try:
            resp = await self.httpx.get(stream_url, headers={
                "Referer"    : referer,
                "User-Agent" : "Mozilla/5.0 (X11; Linux x86_64; rv:101.0) Gecko/20100101 Firefox/101.0",
            }, follow_redirects=True)
            content = resp.text
        except Exception:
            return stream_url, referer

        if not content.strip().startswith("#EXTM3U"):
            return stream_url, referer

        return self._parse_m3u8(content, stream_url)