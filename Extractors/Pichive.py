# Bu araç @keyiflerolsun tarafından | @KekikAkademi için yazılmıştır.
# Python portu: Kekik-cloudstream / DizillaPlugin.kt -> registerExtractorAPI(Pichive()) & FourPichive()

from typing import Any, List, Optional, Union

from Core.Extractor.ContentXPlayer import ContentXPlayer
from Core.Extractor.ExtractorBase import ExtractorBase
from Core.Extractor.ExtractorModels import ExtractResult


class PichiveExtractor(ContentXPlayer, ExtractorBase):
    """Pichive / FourPichive (Dizilla) çözücüsü.

    Kotlin'de ``Pichive`` ve ``FourPichive``, ``ContentX``'in alt sınıflarıdır
    (``class Pichive : ContentX()``). Akış aynıdır:

        1. ``iframe.php`` -> ``window.openPlayer('<playList>', ...)``
        2. ``source2.php?v=<playList>`` -> ``{"playlist":[{"sources":[{"type":"hls", "file": ".../m.php?v=..."}]}]}``
        3. ``m.php`` -> ``master.m3u8`` (720p + 1080p varyant, 2 ses parçası)
        4. **Kritik:** HLS isteklerinde ``Referer`` *m.php adresi* olmak zorundadır;
           iframe adresi, site adresi ya da boş referer verilirse sunucu 404 döner.
    """

    name     = "Pichive"
    main_url = "https://pichive.online"

    # four.pichive.online / pichive.online (ve olası diğer alt alan adları)
    supported_domains = [
        "pichive.online",
        "pichive.com",
    ]

    def can_handle_url(self, url: str) -> bool:
        if not url:
            return False
        return any(domain in url for domain in self.supported_domains) and (
            "/iframe.php" in url or "/iframe" in url or "/embed" in url
        )

    def get_source_label(self, url: str) -> str:
        return f"{self.name} ({url.split('//')[-1].split('/')[0]})"

    async def extract(
        self, url: str, referer: Optional[str] = None, **kwargs: Any
    ) -> Optional[Union[ExtractResult, List[ExtractResult]]]:
        return await self.resolve(url, referer=referer, extractor_name=self.name)


# Geriye dönük uyumluluk için alias
Pichive = PichiveExtractor
