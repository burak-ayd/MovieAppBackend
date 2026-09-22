import re
from datetime import date, datetime
from typing import List, Literal, Optional, Union, Dict, Any
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class SearchResult(BaseModel):
    """Arama sonucunda dönecek veri modeli."""
    model_config = ConfigDict(extra="allow")

    title      : str
    url        : str
    poster     : Optional[str] = None
    plugin     : Optional[str] = None   # Hangi plugin'den geldiği bilgisi
    year       : Optional[Union[int, str]] = None
    media_type : Optional[str] = "movie"
    metadata   : Dict[str, Any] = Field(default_factory=dict)

    def __str__(self) -> str:
        # Tekli yazdırmalarda JSON formatında güzelce basar
        return self.model_dump_json(indent=4)

    def __repr__(self) -> str:
        # Liste içinde yazdırıldığında da aynı güzel formatı korur
        return self.__str__()

class MainPageResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    title        : Optional[str] = None
    url          : Optional[str] = None
    category     : Optional[str] = ""
    poster       : Optional[str] = None
    plugin     : Optional[str] = None
    language     : Optional[str] = None
    release_date : Optional[str] = None
    rating         : Optional[str] = None

    def __str__(self) -> str:
        return self.model_dump_json(indent=4)

    def __repr__(self) -> str:
        return self.__str__()

class Episode(BaseModel):
    model_config = ConfigDict(extra="allow")

    season         : Optional[int] = None
    episode        : Optional[int] = None
    season_number  : Optional[int] = None
    episode_number : Optional[int] = None
    title          : Optional[str] = None
    url            : Optional[str] = None

    @model_validator(mode="after")
    def sync_season_episode(self) -> "Episode":
        if self.season is None and self.season_number is not None:
            self.season = self.season_number
        if self.episode is None and self.episode_number is not None:
            self.episode = self.episode_number
        if not self.title:
            self.title = ""
        if any(keyword in self.title.lower() for keyword in ["bölüm", "sezon", "episode"]):
            self.title = ""
        return self


    @model_validator(mode="after")
    def check_title(self) -> "Episode":
        if not self.title:
            self.title = ""

        if any(keyword in self.title.lower() for keyword in ["bölüm", "sezon", "episode"]):
            self.title = ""

        return self
    def __str__(self) -> str:
        # Tekli yazdırmalarda JSON formatında güzelce basar
        return self.model_dump_json(indent=4)

    def __repr__(self) -> str:
        # Liste içinde yazdırıldığında da aynı güzel formatı korur
        return self.__str__()

class SeriesInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    content_type : Optional[str]           = "series"
    url          : Optional[str]           = None
    poster       : Optional[str]           = None
    title        : Optional[str]           = None
    description  : Optional[str]           = None
    tags         : Optional[str]           = None
    rating       : Optional[str]           = None
    year         : Optional[str]           = None
    actors       : Optional[str]           = None
    episodes     : Optional[List[Episode]] = None
    plugin       : Optional[str]           = None
    seasons      : Optional[Union[Dict[Any, Any], int, str, list]] = None

    @field_validator("tags", "actors", mode="before")
    @classmethod
    def convert_lists(cls, value):
        return ", ".join(value) if isinstance(value, list) else value

    @field_validator("rating", "year", mode="before")
    @classmethod
    def ensure_string(cls, value):
        return str(value) if value is not None else value
    def __str__(self) -> str:
        # Tekli yazdırmalarda JSON formatında güzelce basar
        return self.model_dump_json(indent=4)

    def __repr__(self) -> str:
        # Liste içinde yazdırıldığında da aynı güzel formatı korur
        return self.__str__()

class MovieInfo(BaseModel):
    """Bir medya öğesinin bilgilerini tutan model."""
    model_config = ConfigDict(extra="allow")

    # --- Kaynak ---
    content_type    : Optional[str]  = "movie"
    url             : str
    plugin          : Optional[str]  = None

    # --- Temel bilgiler ---
    title           : Optional[str]  = None
    original_title  : Optional[str]  = None   # Orijinal dil başlığı
    slug            : Optional[str]  = None   # URL için: "breaking-bad"
    description     : Optional[str]  = None   # Özet / açıklama (overview)
    tagline         : Optional[str]  = None   # Slogan

    # --- Görseller ---
    poster_url          : Optional[str]  = None   # Afiş (dikey)
    backdrop_url    : Optional[str]  = None   # Arka plan (yatay)
    fragman_url         : Optional[str]  = None   # Fragman linki (trailer_url)

    # --- Detaylar ---
    release_date            : Optional[str]  = None   # Çıkış yılı / tarihi (release_date)
    end_date        : Optional[str]  = None   # Bitiş tarihi (dizi için)
    status          : Optional[Literal[
        'rumored', 'pre-production', 'in-production',
        'post-production', 'released', 'canceled', 'ended',
        'returning-series', 'pilot'
    ]]               = 'released'
    country         : Optional[str]  = None   # Yapım ülkesi: "US", "TR"
    language        : Optional[str]  = None   # Orijinal dil: "en", "tr"
    runtime_minutes : Optional[int]  = 0   # Süre (dakika)
    rating          : Optional[str]  = None   # 0.0 - 10.0
    vote_count      : Optional[int]  = 0   # IMDb oy sayısı
    age_rating      : Optional[str]  = None   # "G", "PG", "PG-13", "R", "TV-MA", "+18"
    genre           : Optional[list[str]] = []

    # --- Dış referanslar ---
    imdb_id            : Optional[str]  = None   # tt1234567

    # --- Yönetici / yapım ---
    director        : Optional[str]  = None   # Film yönetmeni
    creator         : Optional[str]  = None   # Dizi yaratıcısı
    cast_members    : Optional[list[str]] = []  # Oyuncu listesi (cast_members)
    production_co   : Optional[str]  = None   # Yapım şirketi

    # --- Yönetim ---
    is_featured     : bool           = False  # Anasayfada öne çıkar
    def __str__(self) -> str:
        # Tekli yazdırmalarda JSON formatında güzelce basar
        return self.model_dump_json(indent=4)

    def __repr__(self) -> str:
        # Liste içinde yazdırıldığında da aynı güzel formatı korur
        return self.__str__()

    # @field_validator("backdrop_url",mode="before")
    # @classmethod
    # def convert_backdrop_url(cls, value):
    #     if value is None:
    #         return None
    @field_validator("slug", mode="before")
    @classmethod
    def auto_slug(cls, value):
        """slug boşsa None döndür; dolu gelirse olduğu gibi kullan."""
        if value:
            return value.strip()
        return None

    @field_validator("fragman_url", mode="before")
    @classmethod
    def convert_youtube_url(cls, value):
        if value is None:
            return None
        value = value.replace("trailer/", "")
        return "https://www.youtube.com/watch?v=" + value

    @field_validator("rating", mode="before")
    @classmethod
    def ensure_string(cls, value):
        return str(value) if value is not None else value

class Subtitle(BaseModel):
    url: str
    language: str = "tr"
    label: Optional[str] = "Türkçe"
