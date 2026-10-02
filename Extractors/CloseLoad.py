"""FilmMakinesi CloseLoad oynatıcısı.

Kotlin kaynak: Kekik-cloudstream/FilmMakinesi — CloseLoadExtractor.kt
Ortak çözümleme mantığı `_fmk_base.py` içinde.
"""

from Core.Extractor.Players.FilmMakinesiBase import FilmMakinesiBase


class CloseLoadExtractor(FilmMakinesiBase):
    """FilmMakinesi CloseLoad oynatıcısı (closeload.filmmakinesi.to)."""

    name = "CloseLoad"
    main_url = "https://closeload.filmmakinesi.to"
    domains = [
        "closeload.filmmakinesi.to",
        "closeload.filmmakinesi.film",
        "closeload.closeload.com",
    ]

    def can_handle_url(self, url: str) -> bool:
        return any(domain in url for domain in self.domains)


# Geriye dönük uyumluluk alias'ı
CloseLoad = CloseLoadExtractor
