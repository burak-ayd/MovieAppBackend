from Core.Extractor.ExtractorBase import ExtractorBase
from Core.Extractor.ExtractorLoader import ExtractorLoader
import urllib.parse

class ExtractorManager:
    def __init__(self, extractor_dir="Extractors"):
        # Çıkarıcı yükleyiciyi başlat ve tüm çıkarıcıları yükle
        self.extractor_loader = ExtractorLoader(extractor_dir)
        self.extractors       = self.extractor_loader.load_all()

    def find_extractor(self, link) -> ExtractorBase:
        # Verilen bağlantıyı işleyebilecek çıkarıcıyı bul
        for extractor_cls in self.extractors:
            extractor:ExtractorBase = extractor_cls()
            if extractor.can_handle_url(link):
                return extractor

        return None

    @staticmethod
    def _display_url(link: str) -> str:
        """Picker'da göstermek için URL'yi domain'den arındırıp sadece path+query bırakır."""
        try:
            parsed = urllib.parse.urlparse(link)
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            return path
        except Exception:
            return link

    def map_links_to_extractors(self, links) -> dict:
        # Bağlantıları uygun çıkarıcılarla eşleştir
        mapping = {}
        for link in links:
            for extractor_cls in self.extractors:
                extractor:ExtractorBase = extractor_cls()
                if extractor.can_handle_url(link):
                    label = getattr(extractor, "get_source_label", lambda u: extractor.name)(link)
                    mapping[link] = f"{label:<30} » {self._display_url(link)}"
                    break

        return mapping