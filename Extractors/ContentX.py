# Oluşturan: Burak Aydoğan

from typing import Any, List, Optional, Union

from Core.Extractor.ContentXPlayer import ContentXPlayer
from Core.Extractor.ExtractorBase import ExtractorBase
from Core.Extractor.ExtractorModels import ExtractResult


class ContentXExtractor(ContentXPlayer, ExtractorBase):
    """ContentX oynatıcı ailesi çözücüsü.

    Kotlin'de ``ContentX`` tek bir sınıftır; ``FourCX`` (four.contentx.me),
    ``PlayRu`` (playru.net), ``FourPlayRu`` (four.playru.net) ve ``SNplayer``
    (sn.dplayer82.site) yalnızca ``mainUrl`` değiştirerek ondan türetilmiştir.
    ExtractorLoader dosya başına tek sınıf yüklediği için bu alt domainler
    ``HOST_LABELS`` içinde toplanır; çıkarıcı adı linkteki host'a göre belirlenir.
    """

    name     = "ContentX"
    main_url = "https://contentx.me"

    # host -> (görünen ad, ana domain)
    HOST_LABELS = {
        "contentx.me":    "ContentX",
        "playru.net":     "PlayRu",
        "dplayer82.site": "SNplayer",
    }

    def can_handle_url(self, url: str) -> bool:
        if not url:
            return False
        return any(domain in url for domain in self.HOST_LABELS) and (
            "/iframe.php" in url or "/iframe" in url or "/embed" in url
        )

    def get_source_label(self, url: str) -> str:
        host = url.split("//")[-1].split("/")[0]
        for domain, label in self.HOST_LABELS.items():
            if domain in host:
                return f"{label} ({host})"
        return f"{self.name} ({host})"

    def _label_for(self, url: str) -> str:
        host = url.split("//")[-1].split("/")[0]
        for domain, label in self.HOST_LABELS.items():
            if domain in host:
                return label
        return self.name

    async def extract(
        self, url: str, referer: Optional[str] = None, **kwargs: Any
    ) -> Optional[Union[ExtractResult, List[ExtractResult]]]:
        return await self.resolve(url, referer=referer, extractor_name=self._label_for(url))


# Geriye dönük uyumluluk için alias
ContentX = ContentXExtractor
