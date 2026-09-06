import re
from typing import Tuple, Optional

class TitleHelper:
    JUNK_PATTERNS = re.compile(
        r'(?i)\b(1080p|720p|4k|uhd|bluray|web-dl|hdrip|turkce\s+dublaj|türkçe\s+dublaj|'
        r'altyazili|altyazılı|tek\s+parca|full\s+hd|film\s+izle|izle|dizi\s+izle)\b'
    )
    YEAR_PATTERN = re.compile(r'\b(19\d\d|20\d\d)\b')

    @classmethod
    def clean(cls, raw_title: str) -> Tuple[str, Optional[int]]:
        year_match = cls.YEAR_PATTERN.search(raw_title)
        year = int(year_match.group(1)) if year_match else None

        cleaned = cls.JUNK_PATTERNS.sub('', raw_title)
        cleaned = re.sub(r'[\(\)\[\]\{\}\-_]', ' ', cleaned)
        cleaned = ' '.join(cleaned.split())
        return cleaned, year
