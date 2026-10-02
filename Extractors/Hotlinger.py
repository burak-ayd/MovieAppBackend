# Oluşturan: Burak Aydoğan

from typing import Any, List, Optional, Union

from Core.Extractor.ContentXPlayer import ContentXPlayer
from Core.Extractor.ExtractorBase import ExtractorBase
from Core.Extractor.ExtractorModels import ExtractResult


class HotlingerExtractor(ContentXPlayer, ExtractorBase):
    """Hotlinger (sn.hotlinger.com) çözücüsü.

    Kotlin'de ``Hotlinger`` doğrudan ``ContentX``'ten türetilmiş ve sadece
    ``name``/``mainUrl`` değiştirilmiştir; mantık ve akış tamamen aynıdır.
    """

    name     = "Hotlinger"
    main_url = "https://sn.hotlinger.com"

    supported_domains = [
        "hotlinger.com",
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
        # Kotlin'de hotlinger için m.php -> master.m3u8 dönüşümü şart;
        # ortak sınıf her iki adayı da denediği için ek işlem gerekmiyor.
        return await self.resolve(url, referer=referer, extractor_name=self.name)


# Geriye dönük uyumluluk için alias
Hotlinger = HotlingerExtractor
