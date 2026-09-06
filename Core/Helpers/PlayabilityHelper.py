import httpx
from typing import Optional

class PlayabilityHelper:
    """Canlılık kontrolü yapan hafif HTTP HEAD istemcisi."""

    @staticmethod
    async def is_alive(url: str, timeout: float = 5.0) -> bool:
        """URL'nin erişilebilir olup olmadığını HEAD isteği ile kontrol eder."""
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.head(url, follow_redirects=True)
                return resp.status_code < 400
        except Exception:
            return False
