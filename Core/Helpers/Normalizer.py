import re
import unicodedata

class Normalizer:
    """Metin ve slug normalizasyonu."""

    @staticmethod
    def slugify(text: str) -> str:
        """Metni URL-uyumlu slug formatına çevirir."""
        text = unicodedata.normalize('NFKD', text)
        text = text.encode('ascii', 'ignore').decode('ascii')
        text = text.lower()
        text = re.sub(r'[^\w\s-]', '', text)
        text = re.sub(r'[-\s]+', '-', text).strip('-')
        return text

    @staticmethod
    def normalize_text(text: str) -> str:
        """Metni karşılaştırma için normalize eder."""
        text = text.lower().strip()
        text = re.sub(r'\s+', ' ', text)
        return text
