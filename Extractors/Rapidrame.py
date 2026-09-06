import json
import re
import urllib.parse
from typing import Any, Dict, List, Optional

from Core.Extractor.ExtractorBase import ExtractorBase
from Core.Extractor.ExtractorModels import ExtractResult

# Subtitle modelini güvenli şekilde içe aktar
try:
    from Core.Plugin.PluginModels import Subtitle
except ImportError:
    try:
        from Core.Extractor.ExtractorModels import Subtitle
    except ImportError:
        Subtitle = None


class JsUnpacker:
    """Dean Edwards p.a.c.k.e.r şifreli JavaScript kodlarını çözer."""

    @staticmethod
    def unpack(packed: str) -> str:
        pattern = r"\}\('(.*?)'\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*'(.*?)'\.split\('\|'\)"
        match = re.search(pattern, packed, re.DOTALL)
        if not match:
            pattern_alt = r"eval\(function\(p,a,c,k,e,[rd]\)\{.*return p\}\('(.*?)'\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*'(.*?)'\.split\('\|'\)"
            match = re.search(pattern_alt, packed, re.DOTALL)
            if not match:
                return packed

        payload, radix, count, symtab = match.groups()
        radix = int(radix)
        count = int(count)
        words = symtab.split("|")

        def base_encode(num: int, b: int) -> str:
            chars = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
            if num == 0:
                return chars[0]
            res = []
            while num > 0:
                res.append(chars[num % b])
                num //= b
            return "".join(reversed(res))

        lookup = {}
        for i in range(count):
            key = base_encode(i, radix)
            lookup[key] = words[i] if i < len(words) and words[i] else key

        def replace_word(m):
            word = m.group(0)
            return lookup.get(word, word)

        return re.sub(r"\b\w+\b", replace_word, payload)


class RapidrameExtractor(ExtractorBase):
    """
    HDFilmCehennemi & Rapidrame Video Barındırıcı Çözücüsü.
    Desteklenenler: hdfilmcehennemi.mobi, rapidrame, dahili player sekmeleri (/152613 vb.)
    """

    name = "Rapidrame"
    main_url = "https://hdfilmcehennemi.mobi"
    domains = [
        "rapidrame",
        "hdfilmcehennemi.mobi",
        "hdfilmcehennemi.nl",
        "hdfilmcehennemi.cx",
    ]

    def __init__(self):
        super().__init__()

    def can_handle_url(self, url: str) -> bool:
        """Taban sınıftaki tekil main_url kontrolünü çoklu domain desteği ile genişletir."""
        return any(domain in url for domain in self.domains)

    async def extract(
        self, url: str, referer: Optional[str] = None, **kwargs: Any
    ) -> Optional[ExtractResult]:
        # Molystream / Rapidrame anti-hotlink koruması için ana site referer'ı zorunludur[cite: 7]
        base_referer = referer or "https://www.hdfilmcehennemi.nl/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Referer": base_referer,
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        }

        # 1. Aşama: Link bir ara sekme ise (/152613 gibi), içindeki asıl iframe'i al
        if "video/embed" not in url:
            try:
                resp = await self.client.get(url, headers=headers)
                iframe_match = re.search(
                    r'<iframe[^>]+(?:data-src|src)=["\']([^"\']+)["\']', resp.text
                )
                if iframe_match:
                    url = self.fix_url(iframe_match.group(1))
                else:
                    return None
            except Exception as e:
                print(f"[!] {self.name} ara sekme çözümleme hatası ({url}): {e}")
                return None

        # 2. Aşama: Embed sayfasına git
        embed_domain = urllib.parse.urlparse(url).netloc
        embed_headers = headers.copy()
        embed_headers["Referer"] = base_referer

        try:
            embed_resp = await self.client.get(url, headers=embed_headers)
            html_content = embed_resp.text

            # Dean Edwards Packer JS kontrolü ve açma
            if "eval(function(p,a,c,k,e," in html_content:
                html_content = JsUnpacker.unpack(html_content)

            # 3. Aşama: Akış (.m3u8 veya direct stream) linkini ayıkla
            stream_url = None

            # Model 1: file: "..." veya source: "..."
            file_match = re.search(
                r'(?:file|source|src)\s*:\s*["\'](https?://[^"\']+\.m3u8[^"\']*)["\']',
                html_content,
            )
            if file_match:
                stream_url = file_match.group(1)

            # Model 2: sources: [...] JSON bloğu
            if not stream_url:
                sources_match = re.search(
                    r'sources\s*:\s*(\[.*?\])\s*(?:,|\n|;)', html_content, re.DOTALL
                )
                if sources_match:
                    try:
                        sources = json.loads(sources_match.group(1))
                        if sources and isinstance(sources, list):
                            stream_url = sources[0].get("file")
                    except Exception:
                        pass

            # Model 3: HTML5 <source> etiketi
            if not stream_url:
                source_tag = re.search(
                    r'<source[^>]+src=["\'](https?://[^"\']+\.m3u8[^"\']*)["\']',
                    html_content,
                )
                if source_tag:
                    stream_url = source_tag.group(1)

            # Model 4: Metin içerisindeki saf m3u8 adresi
            if not stream_url:
                raw_m3u8 = re.search(
                    r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']', html_content
                )
                if raw_m3u8:
                    stream_url = raw_m3u8.group(1)

            if not stream_url:
                return None

            # 4. Aşama: Altyazıları ayıkla
            subtitles = []
            tracks_match = re.search(
                r'tracks\s*:\s*(\[.*?\])\s*(?:,|\n|;)', html_content, re.DOTALL
            )
            if tracks_match:
                try:
                    tracks = json.loads(tracks_match.group(1))
                    for t in tracks:
                        if t.get("kind") in ["captions", "subtitles"] and t.get("file"):
                            sub_url = self.fix_url(t.get("file"))
                            lang = t.get("label", "tr")
                            if Subtitle:
                                subtitles.append(
                                    Subtitle(
                                        url=sub_url,
                                        language=lang,
                                        label=t.get("label", "Türkçe"),
                                    )
                                )
                            else:
                                subtitles.append(
                                    {
                                        "url": sub_url,
                                        "language": lang,
                                        "format": "vtt" if ".vtt" in sub_url else "srt",
                                    }
                                )
                except Exception:
                    pass

            # MPV / VLC veya ExoPlayer için gerekli HTTP başlıkları
            stream_headers = {
                "User-Agent": headers["User-Agent"],
                "Referer": f"https://{embed_domain}/",
                "Origin": f"https://{embed_domain}",
            }

            return ExtractResult(
                stream_url=stream_url.replace(r"\/", "/"),
                quality="auto",
                headers=stream_headers,
                subtitles=subtitles,
                is_m3u8=True,
            )

        except Exception as e:
            print(f"[!] {self.name} extract hatası ({url}): {e}")
            return None