"""FilmMakinesi Rapid oynatıcısı.

Kotlin kaynak: Kekik-cloudstream/FilmMakinesi — RapidExtractor.kt
Ortak çözümleme mantığı `_fmk_base.py` içinde.
"""

from Core.Extractor.Players.FilmMakinesiBase import FilmMakinesiBase


class RapidFilmMakinesiExtractor(FilmMakinesiBase):
    """FilmMakinesi Rapid oynatıcısı (rapid.filmmakinesi.to)."""

    name = "Rapid"
    main_url = "https://rapid.filmmakinesi.to"
    domains = [
        "rapid.filmmakinesi.to",
        "rapid.filmmakinesi.film",
    ]

    def can_handle_url(self, url: str) -> bool:
        return any(domain in url for domain in self.domains)


# Geriye dönük uyumluluk alias'ı
Rapid = RapidFilmMakinesiExtractor
