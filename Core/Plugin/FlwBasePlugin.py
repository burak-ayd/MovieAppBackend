from abc import abstractmethod
from typing import List, Union, Dict, Optional
import httpx
from Core.Plugin.PluginBase import PluginBase
from Core.Plugin.PluginModels import SearchResult, MainPageResult, MovieInfo, SeriesInfo

class FlwBasePlugin(PluginBase):
    """Yönlendirme (redirect) zincirlerini çözen özel taban sınıf.
    
    Bazı siteler, içerik sayfalarına erişmeden önce birden fazla 
    yönlendirme (301/302 redirect) uygular. Bu sınıf, redirect 
    zincirini takip edip son hedef URL'yi döndürür.
    """

    async def resolve_redirect(self, url: str) -> str:
        """Redirect zincirini takip ederek son URL'yi döner."""
        try:
            resp = await self.client.get(url)
            return str(resp.url)
        except Exception:
            return url

    async def get_final_url(self, url: str, max_redirects: int = 5) -> str:
        """Belirli sayıda redirect takip ederek son URL'yi döner."""
        current_url = url
        for _ in range(max_redirects):
            try:
                async with httpx.AsyncClient(
                    follow_redirects=False, timeout=10.0
                ) as client:
                    resp = await client.get(current_url, headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    })
                    if resp.status_code in (301, 302, 303, 307, 308):
                        location = resp.headers.get("location", "")
                        if location.startswith("/"):
                            from urllib.parse import urlparse
                            parsed = urlparse(current_url)
                            location = f"{parsed.scheme}://{parsed.netloc}{location}"
                        current_url = location
                    else:
                        break
            except Exception:
                break
        return current_url
