from abc import ABC, abstractmethod
from typing import List, Union, Dict, Optional
import re
from urllib.parse import urljoin

from cloudscraper import CloudScraper
from httpx import AsyncClient, Timeout

from Core.Plugin.PluginModels import SearchResult, MainPageResult, MovieInfo, SeriesInfo
from Core.Helpers.HTMLHelper import HTMLHelper

class PluginBase(ABC):
    name: str = "Plugin"
    language: str = "tr"
    main_url: str = "https://example.com"
    description: str = "No description provided."
    favicon     = f"https://www.google.com/s2/favicons?domain={main_url}&sz=64"
    main_page: Dict[str, str] = {}

    async def url_update(self, new_url: str):
        self.favicon   = f"https://www.google.com/s2/favicons?domain={new_url}&sz=64"
        self.main_page = {url.replace(self.main_url, new_url): category for url, category in self.main_page.items()}
        self.main_url  = new_url

    def __init__(self):
        self.httpx = AsyncClient(
            headers = {
                "User-Agent" : "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_5)",
                "Accept"     : "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            timeout = Timeout(10.0),
            follow_redirects = True,
        )
        self.cloudscraper  = CloudScraper()
        self.httpx.headers.update(self.cloudscraper.headers)
        self.httpx.cookies.update(self.cloudscraper.cookies)
        self.client = self.httpx

    async def close(self):
        """HTTP oturumunu güvenli bir şekilde kapatır."""
        await self.httpx.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


    @abstractmethod
    async def get_main_page(self, page: int, url: str, category: str) -> List[MainPageResult]:
        """Kategori veya ana sayfa listelemesini çeker."""
        pass

    @abstractmethod
    async def search(self, query: str) -> List[SearchResult]:
        """Site üzerinde arama yapar."""
        pass

    @abstractmethod
    async def load_item(self, url: str) -> Union[MovieInfo, SeriesInfo]:
        """İçerik sayfasından detay meta verilerini döner."""
        pass

    @abstractmethod
    async def load_links(self, url: str) -> List[str]:
        """İzleme sayfasındaki video oynatıcı (embed/iframe) bağlantılarını toplar."""
        pass

    async def async_cf_get(self, url: str, headers: Optional[Dict[str, str]] = None) -> str:
        """Cloudflare korumalı sayfaları curl_cffi üzerinden aşar."""
        return await HTMLHelper.fetch_cf(url, headers=headers)

    def fix_url(self, url: str) -> str:
        if not url:
            return ""

        if url.startswith("http") or url.startswith("{\""):
            return url

        return f"https:{url}" if url.startswith("//") else urljoin(self.main_url, url)

    @staticmethod
    def clean_title(title: str) -> str:
        suffixes = [
            " izle", 
            " full film", 
            " filmini full",
            " full türkçe",
            " alt yazılı", 
            " altyazılı", 
            " tr dublaj",
            " hd türkçe",
            " türkçe dublaj",
            " yeşilçam ",
            " erotik fil",
            " türkçe",
            " yerli",
            " tüekçe dublaj",
        ]

        cleaned_title = title.strip()

        for suffix in suffixes:
            cleaned_title = re.sub(f"{re.escape(suffix)}.*$", "", cleaned_title, flags=re.IGNORECASE).strip()

        return cleaned_title