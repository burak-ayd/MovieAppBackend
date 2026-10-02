# STREAM: MODÜLER MEDYA KAZIMA, İNDEKSLEME VE JIT ÇÖZÜMLEME MİMARİSİ

## AI Agent Master Implementation & Architecture Specification

> **Hedef:** Bu doküman, `STREAM` projesini sıfırdan kuracak otonom kodlama ajanları (AI Coding Agents) veya kıdemli geliştiriciler için hazırlanmış uçtan uca teknik uygulama şartnamesidir. Klasör hiyerarşisi, Windows import izolasyon protokolleri, Supabase DDL şeması, veri modelleri ve tüm iş akışları bağlayıcı kurallarla tanımlanmıştır.

---

## 1. MİMARİ VİZYON VE ÇALIŞMA PRENSİPLERİ

Sistem, modüler, tak-çalıştır (Plug & Play) eklenti desteğine sahip bir hibrit medya motorudur:

1. **Veritabanında Yalnızca Sayfa URL'i Tutma (Zero Link Rot):**
    - Video sağlayıcılarının (.m3u8, direct mp4, vidmoly embed vb.) stream URL'leri IP kilitli veya kısa ömürlü (token süreli) olduğundan veritabanında kesinlikle ham video linki saklanmaz.
    - Supabase veritabanında sadece kaynağın kanonik sayfa adresi (`page_url`) ve TMDB ile zenginleştirilmiş meta veriler tutulur.
2. **Just-in-Time (JIT) Resolver:**
    - Kullanıcı izleme talebinde bulunduğunda sistem anlık olarak ilgili plugin'in `load_links` metodunu ve ardından `ExtractorManager`'ın `extract` metodunu tetikleyerek o saniyede taze stream linkini çıkarır ve oynatıcıya (VLC/MPV) iletir.
3. **Sayfa Kaymasını Önleyen Tarama (Reverse Backfill):**
    - Sitelerin son sayfalarındaki eski içerikler sabit kaldığı için arşiv taramaları sitenin en son sayfasından geriye doğru (`max_page` -> `1`) işletilir.
    - Günlük delta tarayıcı ise yalnızca ilk 1-2 sayfayı tarar ve veritabanında daha önce görülen bir linke rastladığı anda işlemi durdurur.
4. **Çalışma Anı Keşfi (Local-First Discovery):**
    - `Plugins/` ve `Extractors/` dizinlerine yeni bir dosya bırakıldığında ana kod tabanında değişiklik yapılmaz; dinamik yükleyiciler bu modülleri anında keşfeder.

---

## 2. WINDOWS IMPORT VE ORTAM KURALLARI (KRİTİK)

Windows ve Python ortamında yaşanan `ModuleNotFoundError: No module named 'Core'` ve dairesel import (circular dependency) problemlerini tamamen engellemek için **aşağıdaki 4 kurala katı bir şekilde uyulacaktır**:

1. **Paket Belirteçleri (`__init__.py`):**
    - Ağaçtaki tüm alt klasörlerin içinde (`Core`, `Core/Extractor`, `Core/Helpers`, `Core/Media`, `Core/Libs`, `Core/Plugin`, `Extractors`, `Plugins`) mutlaka bir `__init__.py` dosyası oluşturulmalıdır.
2. **Kök Tabanlı Mutlak Importlar (Absolute Imports):**
    - Göreli importlar (`from ..Helpers import ...` veya `from PluginModels import ...`) **kesinlikle yasaktır**.
    - Her zaman proje kökünü (`Core...`) referans alan mutlak yollar kullanılmalıdır:
        ```python
        # DOĞRU:
        from Core.Plugin.PluginModels import SearchResult, Movie
        from Core.Extractor.ExtractorModels import ExtractResult
        from Core.Libs.Supabase import SupabaseClient
        from Core.Helpers.HTMLHelper import HTMLHelper
        ```
3. **Çalıştırma Disiplini:**
    - Kodlar asla alt klasörlerin içinden çalıştırılmamalıdır.
    - Terminal daima projenin ana kök dizininde (`STREAM/`) olmalı ve giriş noktası üzerinden çalıştırılmalıdır:
        ```bash
        python main__.py
        # veya izole bir modül testi için:
        python -m Plugins.HDFilmCehennemi
        ```
4. **sys.path Güvencesi:**
    - `main__.py` dosyasının en başına kök dizini çalışma yoluna garantiyle ekleyen şu blok yazılmalıdır:
        ```python
        import sys
        from pathlib import Path
        ROOT_DIR = Path(__file__).resolve().parent
        if str(ROOT_DIR) not in sys.path:
            sys.path.insert(0, str(ROOT_DIR))
        ```

---

## 3. PROJE KLASÖR HİYERARŞİSİ VE DOSYA GÖREVLERİ

```text
STREAM/
│   requirements.txt              # Proje kütüphaneleri (httpx, pydantic, supabase, rapidfuzz vb.)
│   main__.py                   # CLI giriş noktası, orkestratör ve test yürütücüsü
│   .env                          # API anahtarları (SUPABASE_URL, TMDB_API_KEY vb.)
│
├───Core/
│   │   __init__.py
│   │
│   ├───Extractor/                # Video Oynatıcı Çözücü Çekirdeği
│   │       ExtractorBase.py      # BaseExtractor soyut sınıfı (ABC)
│   │       ExtractorLoader.py    # Extractors/ dizinini dinamik tarayıp yükleyen sınıf
│   │       ExtractorManager.py   # Embed linkini domain'e göre doğru çözücüye yönlendiren yönetici
│   │       ExtractorMixins.py    # Şifre çözme (Packer, CryptoJS, Deobfuscation) yardımcıları
│   │       ExtractorModels.py    # ExtractResult, ExtractedStream modelleri
│   │       VideoPlayerExtractor.py # Standart HTML5 video ve genel iframe ayrıştırıcı
│   │       YTDLPCache.py         # yt-dlp tabanlı çözümlemeler için bellek/disk önbelleği
│   │       __init__.py
│   │
│   ├───Helpers/                  # Ortak Yardımcı Katman
│   │       FallbackClients.py    # User-Agent rotasyonu ve yedek HTTP proxy havuzu
│   │       HTMLHelper.py         # Cloudflare bypass (curl_cffi/httpx) ve HTML ayrıştırma wrapper'ı
│   │       MetadataHelper.py     # Yıl, tür, süre ve IMDb ID ayıklayıcı
│   │       MethodCache.py        # TTL destekli in-memory async cache dekoratörü
│   │       Normalizer.py         # Metin ve slug normalizasyonu
│   │       PlayabilityHelper.py  # Canlılık kontrolü yapan hafif HTTP HEAD istemcisi
│   │       SubtitleHelper.py     # VTT/SRT altyazı normalize edici ve formatlayıcı
│   │       TitleHelper.py        # Başlık temizleyici (Sanitizer) ve Regex filtresi
│   │       __init__.py
│   │
│   ├───Media/                    # Medya Yürütme Katmanı
│   │       MediaHandler.py       # VLC / MPV alt süreç (subprocess) komut motoru
│   │       MediaManager.py       # Medya türüne göre uygun extractor ve oynatıcı koordinatörü
│   │       __init__.py
│   │
│   ├───Libs/                     # Dış Servis Entegrasyonları
│   │       Supabase.py           # Supabase PostgreSQL istemcisi (Sources, CrawlerState)
│   │       TMDB.py               # TMDB API v3 istemcisi (IMDb find, Search, Rapidfuzz matching)
│   │       __init__.py
│   │
│   └───Plugin/                   # Kaynak Site Kazıyıcı Çekirdeği
│           FlwBasePlugin.py      # Yönlendirme (redirect) zincirlerini çözen özel taban sınıf
│           PluginBase.py         # Tüm site eklentilerinin uyması gereken Abstract Base Class
│           PluginLoader.py       # Plugins/ dizinindeki siteleri çalışma anında keşfeden modül
│           PluginManager.py      # Paralel arama ve ana sayfa listeleme yöneticisi
│           PluginModels.py       # SearchResult, MainPageResult, Movie, Episode, SeriesInfo
│           __init__.py
│
├───Extractors/                   # Somut Video Barındırıcı Çözücüleri
│       Vidmoly.py
│       Filemoon.py
│       __init__.py
│
└───Plugins/                      # Somut Kaynak Site Kazıyıcıları
        HDFilmCehennemi.py
        Dizilla.py
        __init__.py

```

---

## 4. SUPABASE VERİTABANI ŞEMASI (SQL DDL)

Uygulama çalıştırılmadan önce Supabase PostgreSQL üzerinde şu tablolar hazır olmalıdır:

```sql
-- 1. TMDB Normalized Medya Tablosu
CREATE TABLE IF NOT EXISTS media (
    id TEXT PRIMARY KEY,                 -- örn: 'tmdb-movie-550' veya 'tmdb-tv-1399'
    tmdb_id INTEGER NOT NULL,
    media_type TEXT CHECK (media_type IN ('movie', 'tv')) NOT NULL,
    imdb_id TEXT,
    title TEXT NOT NULL,
    original_title TEXT,
    release_year INTEGER,
    poster_path TEXT,
    overview TEXT,
    vote_average NUMERIC(3, 1),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Kaynak Sayfa URL Tablosu (JIT Çözümleme İçin - Kesinlikle ham video linki tutulmaz)
CREATE TABLE IF NOT EXISTS sources (
    id BIGSERIAL PRIMARY KEY,
    media_id TEXT REFERENCES media(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,              -- örn: 'HDFilmCehennemi'
    page_url TEXT NOT NULL,              -- örn: '/film/matrix-izle/'
    title_scraped TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    fail_count INTEGER DEFAULT 0,
    last_checked TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT unique_provider_page UNIQUE (provider, page_url)
);

CREATE INDEX IF NOT EXISTS idx_sources_media_id ON sources(media_id);
CREATE INDEX IF NOT EXISTS idx_sources_provider ON sources(provider);

-- 3. Sayfa Kaymasını Önleyen Tarama Durum Tablosu
CREATE TABLE IF NOT EXISTS crawler_state (
    provider TEXT PRIMARY KEY,
    daily_last_checked TIMESTAMPTZ,
    backfill_page INTEGER DEFAULT 1,     -- Geriye doğru taranan sayfa
    max_page INTEGER DEFAULT 100,        -- Sitenin toplam sayfa sayısı
    is_backfill_completed BOOLEAN DEFAULT FALSE,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4. Alan Adı Değişikliklerini Yöneten Ayar Tablosu
CREATE TABLE IF NOT EXISTS provider_settings (
    provider TEXT PRIMARY KEY,
    base_url TEXT NOT NULL,
    is_enabled BOOLEAN DEFAULT TRUE,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

```

---

## 5. STANDART VERİ MODELLERİ VE SÖZLEŞMELER

Ajan tüm veri modellerini **Pydantic V2** kullanarak kurmalıdır.

### 5.1. `Core/Plugin/PluginModels.py`

```python
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

class SearchResult(BaseModel):
    title: str
    url: str
    poster: Optional[str] = None
    provider: str
    year: Optional[int] = None
    media_type: str = "movie"
    metadata: Dict[str, Any] = Field(default_factory=dict)

class MainPageResult(BaseModel):
    title: str
    url: str
    category: str
    poster: Optional[str] = None
    provider: str

class Episode(BaseModel):
    season_number: int
    episode_number: int
    title: Optional[str] = None
    url: str

class SeriesInfo(BaseModel):
    title: str
    url: str
    provider: str
    poster: Optional[str] = None
    seasons: Dict[int, List[Episode]] = Field(default_factory=dict)
    description: Optional[str] = None

class Movie(BaseModel):
    """
    Film detay modeli.
    Tekil filmlerin metadata, kaynak sayfası ve embed bağlantılarını taşır.
    """
    title: str
    url: str
    provider: str
    poster: Optional[str] = None
    year: Optional[int] = None
    description: Optional[str] = None
    imdb_id: Optional[str] = None
    tmdb_id: Optional[int] = None
    embed_urls: List[str] = Field(default_factory=list)

class Subtitle(BaseModel):
    url: str
    language: str = "tr"
    label: Optional[str] = "Türkçe"

```

### 5.2. `Core/Extractor/ExtractorModels.py`

```python
from pydantic import BaseModel, Field
from typing import Dict, List, Optional
from Core.Plugin.PluginModels import Subtitle

class ExtractResult(BaseModel):
    stream_url: str                                        # .m3u8 veya direct .mp4 linki
    quality: str = "auto"                                  # 1080p, 720p, auto
    headers: Dict[str, str] = Field(default_factory=dict)  # Referer, User-Agent
    subtitles: List[Subtitle] = Field(default_factory=list)
    is_m3u8: bool = True

```

---

## 6. TABAN SINIFLAR VE YÖNETİCİ KATMANI

### 6.1. `Core/Plugin/PluginBase.py`

```python
from abc import ABC, abstractmethod
from typing import List, Union, Dict, Optional
import httpx
from Core.Plugin.PluginModels import SearchResult, MainPageResult, Movie, SeriesInfo
from Core.Helpers.HTMLHelper import HTMLHelper

class PluginBase(ABC):
    name: str = ""
    language: str = "tr"
    main_url: str = ""
    description: str = ""
    main_page: Dict[str, str] = {}

    def __init__(self):
        self.client = httpx.AsyncClient(
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7"
            },
            timeout=15.0,
            follow_redirects=True
        )

    @abstractmethod
    async def get_main_page(self, page: int, url: str, category: str) -> List[MainPageResult]:
        """Kategori veya ana sayfa listelemesini çeker."""
        pass

    @abstractmethod
    async def search(self, query: str) -> List[SearchResult]:
        """Site üzerinde arama yapar."""
        pass

    @abstractmethod
    async def load_item(self, url: str) -> Union[Movie, SeriesInfo]:
        """İçerik sayfasından detay meta verilerini döner."""
        pass

    @abstractmethod
    async def load_links(self, url: str) -> List[str]:
        """İzleme sayfasındaki video oynatıcı (embed/iframe) bağlantılarını toplar."""
        pass

    async def async_cf_get(self, url: str, headers: Optional[Dict[str, str]] = None) -> str:
        """Cloudflare korumalı sayfaları curl_cffi üzerinden aşar."""
        return await HTMLHelper.fetch_cf(url, headers=headers)

```

### 6.2. `Core/Extractor/ExtractorBase.py`

```python
from abc import ABC, abstractmethod
from typing import List, Optional
import httpx
from Core.Extractor.ExtractorModels import ExtractResult

class BaseExtractor(ABC):
    name: str = ""
    domains: List[str] = []

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=12.0, follow_redirects=True)

    @abstractmethod
    async def extract(self, url: str) -> Optional[ExtractResult]:
        """Iframe/embed linkini çözüp .m3u8 veya direct MP4 akış linkini üretir."""
        pass

```

### 6.3. Dinamik Yükleyiciler ve Yöneticiler

#### `Core/Plugin/PluginLoader.py` & `PluginManager.py`

```python
# Core/Plugin/PluginLoader.py
import importlib
import inspect
from pathlib import Path
from typing import Dict
from Core.Plugin.PluginBase import PluginBase

class PluginLoader:
    @staticmethod
    def load_plugins(plugins_directory: str = "Plugins") -> Dict[str, PluginBase]:
        loaded = {}
        plugin_path = Path(plugins_directory)
        if not plugin_path.exists():
            return loaded

        for file in plugin_path.glob("*.py"):
            if file.name.startswith("__"):
                continue
            module_name = f"{plugins_directory}.{file.stem}"
            module = importlib.import_module(module_name)
            for _, cls in inspect.getmembers(module, inspect.isclass):
                if issubclass(cls, PluginBase) and cls is not PluginBase:
                    instance = cls()
                    loaded[instance.name] = instance
        return loaded

```

```python
# Core/Plugin/PluginManager.py
import asyncio
from typing import List, Dict, Optional
from Core.Plugin.PluginBase import PluginBase
from Core.Plugin.PluginLoader import PluginLoader
from Core.Plugin.PluginModels import SearchResult

class PluginManager:
    def __init__(self, plugins_dir: str = "Plugins"):
        self.plugins_dir = plugins_dir
        self.plugins: Dict[str, PluginBase] = {}

    def initialize(self):
        self.plugins = PluginLoader.load_plugins(self.plugins_dir)

    async def search_all(self, query: str) -> List[SearchResult]:
        tasks = [plugin.search(query) for plugin in self.plugins.values()]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        aggregated = []
        for res in results:
            if isinstance(res, list):
                aggregated.extend(res)
        return aggregated

    def get_plugin(self, name: str) -> Optional[PluginBase]:
        return self.plugins.get(name)

```

#### `Core/Extractor/ExtractorManager.py`

```python
import importlib
import inspect
from pathlib import Path
from typing import List, Optional
from Core.Extractor.ExtractorBase import BaseExtractor
from Core.Extractor.ExtractorModels import ExtractResult

class ExtractorManager:
    def __init__(self, extractors_dir: str = "Extractors"):
        self.extractors_dir = extractors_dir
        self.extractors: List[BaseExtractor] = []

    def initialize(self):
        extractor_path = Path(self.extractors_dir)
        if not extractor_path.exists():
            return
        for file in extractor_path.glob("*.py"):
            if file.name.startswith("__"):
                continue
            module = importlib.import_module(f"{self.extractors_dir}.{file.stem}")
            for _, cls in inspect.getmembers(module, inspect.isclass):
                if issubclass(cls, BaseExtractor) and cls is not BaseExtractor:
                    self.extractors.append(cls())

    async def resolve(self, embed_url: str) -> Optional[ExtractResult]:
        for ext in self.extractors:
            if any(domain in embed_url for domain in ext.domains):
                try:
                    res = await ext.extract(embed_url)
                    if res:
                        return res
                except Exception as e:
                    print(f"[!] Extractor {ext.name} hatası: {e}")
        return None

```

---

## 7. YARDIMCI SINIFLAR VE HARİCİ SERVİSLER

### 7.1. `Core/Helpers/TitleHelper.py`

```python
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

```

### 7.2. `Core/Helpers/HTMLHelper.py`

```python
from curl_cffi.requests import AsyncSession
from typing import Optional, Dict

class HTMLHelper:
    @staticmethod
    async def fetch_cf(url: str, headers: Optional[Dict[str, str]] = None) -> str:
        async with AsyncSession(impersonate="chrome120") as s:
            resp = await s.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                return resp.text
            raise Exception(f"CF Block / Status: {resp.status_code}")

```

### 7.3. `Core/Libs/TMDB.py`

```python
import os
import httpx
from typing import Optional, Dict, Any
from rapidfuzz import fuzz

class TMDBClient:
    def __init__(self):
        self.api_key = os.getenv("TMDB_API_KEY", "")
        self.base_url = "[https://api.themoviedb.org/3](https://api.themoviedb.org/3)"
        self.client = httpx.AsyncClient(timeout=10.0)

    async def find_by_imdb_id(self, imdb_id: str) -> Optional[Dict[str, Any]]:
        url = f"{self.base_url}/find/{imdb_id}"
        resp = await self.client.get(url, params={"api_key": self.api_key, "external_source": "imdb_id"})
        if resp.status_code == 200:
            data = resp.json()
            if data.get("movie_results"):
                return {"media_type": "movie", "data": data["movie_results"][0]}
            if data.get("tv_results"):
                return {"media_type": "tv", "data": data["tv_results"][0]}
        return None

    async def search_best_match(self, title: str, year: Optional[int] = None) -> Optional[Dict[str, Any]]:
        params = {"api_key": self.api_key, "query": title, "language": "tr-TR"}
        if year:
            params["year"] = year

        resp = await self.client.get(f"{self.base_url}/search/multi", params=params)
        if resp.status_code != 200:
            return None

        results = resp.json().get("results", [])
        best_cand = None
        best_score = 0.0

        for item in results:
            target_title = item.get("title") or item.get("name") or ""
            score = fuzz.token_sort_ratio(title.lower(), target_title.lower())
            if score > best_score:
                best_score = score
                best_cand = item

        return best_cand if best_score >= 80.0 else None

```

### 7.4. `Core/Libs/Supabase.py`

```python
import os
from supabase import create_client, Client
from typing import List, Dict, Any, Optional

class SupabaseManager:
    def __init__(self):
        url = os.getenv("SUPABASE_URL", "")
        key = os.getenv("SUPABASE_KEY", "")
        self.client: Client = create_client(url, key)

    def upsert_media(self, media_record: Dict[str, Any]):
        self.client.table("media").upsert(media_record, on_conflict="id").execute()

    def upsert_source(self, media_id: str, provider: str, page_url: str, title: str):
        payload = {
            "media_id": media_id,
            "provider": provider,
            "page_url": page_url,
            "title_scraped": title
        }
        self.client.table("sources").upsert(
            payload,
            on_conflict="provider, page_url",
            ignore_duplicates=True
        ).execute()

    def get_crawler_state(self, provider: str) -> Optional[Dict[str, Any]]:
        res = self.client.table("crawler_state").select("*").eq("provider", provider).execute()
        return res.data[0] if res.data else None

    def update_crawler_state(self, provider: str, backfill_page: int, is_completed: bool = False):
        self.client.table("crawler_state").upsert({
            "provider": provider,
            "backfill_page": backfill_page,
            "is_backfill_completed": is_completed
        }).execute()

```

### 7.5. `Core/Media/MediaHandler.py`

```python
import subprocess
import shutil
from Core.Extractor.ExtractorModels import ExtractResult

class MediaHandler:
    @staticmethod
    def play(result: ExtractResult):
        url = result.stream_url
        headers = result.headers
        referer = headers.get("Referer", "")
        user_agent = headers.get("User-Agent", "")

        # 1. MPV Tercihi
        if shutil.which("mpv"):
            cmd = ["mpv", url]
            if referer:
                cmd.append(f"--referrer={referer}")
            if user_agent:
                cmd.append(f"--user-agent={user_agent}")
            subprocess.Popen(cmd)
            return

        # 2. VLC Tercihi
        vlc_path = shutil.which("vlc") or r"C:\Program Files\VideoLAN\VLC\vlc.exe"
        if shutil.which(vlc_path):
            cmd = [vlc_path, url]
            if referer:
                cmd.append(f":http-referrer={referer}")
            subprocess.Popen(cmd)
            return

        print(f"[!] VLC veya MPV bulunamadı. Stream Linki: {url}")

```

---

## 8. GİRİŞ NOKTASI VE ORKESTRASYON (`main__.py`)

```python
import sys
from pathlib import Path
import asyncio

# 1. Windows Import ve Kök Dizin Kilidi
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from Core.Plugin.PluginManager import PluginManager
from Core.Extractor.ExtractorManager import ExtractorManager
from Core.Libs.Supabase import SupabaseManager
from Core.Libs.TMDB import TMDBClient
from Core.Media.MediaHandler import MediaHandler

async def main():
    print("[*] STREAM Sistemi Başlatılıyor...")

    # Yöneticileri Başlat
    plugin_mgr = PluginManager()
    plugin_mgr.initialize()

    extractor_mgr = ExtractorManager()
    extractor_mgr.initialize()

    db = SupabaseManager()
    tmdb = TMDBClient()

    print(f"[+] Yüklenen Siteler: {list(plugin_mgr.plugins.keys())}")
    print(f"[+] Yüklenen Extractor'lar: {[ext.name for ext in extractor_mgr.extractors]}")

    # Örnek Arama ve JIT Çözümleme Testi
    query = "Matrix"
    print(f"[*] '{query}' için tüm sağlayıcılarda arama yapılıyor...")
    results = await plugin_mgr.search_all(query)

    if results:
        selected = results[0]
        print(f"[+] İlk sonuç seçildi: {selected.title} ({selected.provider})")
        plugin = plugin_mgr.get_plugin(selected.provider)

        print(f"[*] Sayfadan embed linkler alınıyor: {selected.url}")
        embed_links = await plugin.load_links(selected.url)

        for embed_url in embed_links:
            print(f"[*] Extractor çözüyor: {embed_url}")
            stream_info = await extractor_mgr.resolve(embed_url)
            if stream_info:
                print(f"[+] Akış hazır: {stream_info.stream_url}")
                MediaHandler.play(stream_info)
                break

if __name__ == "__main__":
    asyncio.run(main())

```

---

## 9. requirements.txt

```text
httpx>=0.27.0
curl_cffi>=0.7.0
pydantic>=2.7.0
supabase>=2.4.0
python-dotenv>=1.0.1
rapidfuzz>=3.8.0
beautifulsoup4>=4.12.3
yt-dlp>=2024.04.09

```

---

## 10. AI AGENT UYGULAMA KONTROL LİSTESİ (CHECKLIST)

Ajan, projeyi inşa ederken adımları sırasıyla doğrulamalıdır:

- [ ] **Adım 1:** Dizin yapısını eksiksiz kur ve tüm alt klasörlerin içine boş `__init__.py` yerleştir.
- [ ] **Adım 2:** `requirements.txt` dosyasını oluştur ve bağımlılıkları yükle.
- [ ] **Adım 3:** `Core/Plugin/PluginModels.py` içinde `Movie`, `SearchResult`, `MainPageResult`, `SeriesInfo`, `Episode` sınıflarını Pydantic ile kodla.
- [ ] **Adım 4:** `Core/Extractor/ExtractorModels.py` içinde `ExtractResult` modelini tanımla.
- [ ] **Adım 5:** `PluginBase.py` ve `ExtractorBase.py` soyut sınıflarını kur.
- [ ] **Adım 6:** `PluginLoader.py` ve `ExtractorLoader.py` dinamik yükleyicilerini yaz.
- [ ] **Adım 7:** `TitleHelper.py` regex temizleyicisini ve `HTMLHelper.py` curl_cffi Chrome impersonation fonksiyonunu hazırla.
- [ ] **Adım 8:** `TMDB.py` (Fuzzy matching) ve `Supabase.py` (Crawler state ve upsert) istemcilerini oluştur.
- [ ] **Adım 9:** `MediaHandler.py` içinde VLC ve MPV komut satırı argümanlarını (Referer ve UA ekleyerek) bağla.
- [ ] **Adım 10:** En az bir test eklentisi (`Plugins/HDFilmCehennemi.py`) ve bir çözücü (`Extractors/Vidmoly.py`) implemente et.
- [ ] **Adım 11:** Kök dizinde `python __main__.py` çalıştırarak Windows üzerinde mutlak importların hatasız çalıştığını doğrula.

```

***

### Bu Dokümanın Ajana Sağladığı Avantajlar
1. **İç İçe Klasör Çözümü:** `main__.py`'deki kök dizin kilidi ve mutlak import (`from Core...`) yönergeleri, Windows'ta yaşanan import hatalarını kökten engeller.
2. **Mimari Doğruluk:** Video bağlantılarını kaydetmeyip sayfa adresini (`page_url`) saklaması ve izleme anında çözmesi (JIT), veritabanındaki linklerin bozulmasını engeller[cite: 3].
3. **Paginaton Drift Çözümü:** Reverse backfill ve günlük delta ayrımı sayesinde sitelerin sayfa numarası kaymaları güvenle yönetilir[cite: 3].

```
