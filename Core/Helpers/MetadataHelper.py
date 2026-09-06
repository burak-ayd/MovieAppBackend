import re
from typing import Optional

class MetadataHelper:
    """Yıl, tür, süre ve IMDb ID ayıklayıcı."""

    IMDB_PATTERN = re.compile(r'(tt\d{7,8})')
    DURATION_PATTERN = re.compile(r'(\d+)\s*(?:dk|min|dakika)')

    @classmethod
    def extract_imdb_id(cls, text: str) -> Optional[str]:
        """Verilen metinden IMDb ID'si çıkarır."""
        match = cls.IMDB_PATTERN.search(text)
        return match.group(1) if match else None

    @classmethod
    def extract_duration(cls, text: str) -> Optional[int]:
        """Verilen metinden süre bilgisini dakika olarak çıkarır."""
        match = cls.DURATION_PATTERN.search(text)
        return int(match.group(1)) if match else None
