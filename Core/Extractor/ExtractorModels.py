# Bu araç @keyiflerolsun tarafından | @KekikAkademi için yazılmıştır.

from pydantic import BaseModel, field_validator
from typing   import List, Optional
from Core.Helpers.SubtitleHelper import SubtitleHelper


class Subtitle(BaseModel):
    """Altyazı modeli."""
    name : str
    url  : str

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        if isinstance(value, str):
            return SubtitleHelper.normalize_name(value)
        return str(value) if value is not None else "Turkish"



class ExtractResult(BaseModel):
    """Extractor'ın döndürmesi gereken sonuç modeli."""
    name      : str
    url       : str
    referer   : str
    headers   : Optional[dict] = {}
    subtitles : List[Subtitle] = []