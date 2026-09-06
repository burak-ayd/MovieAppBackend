import re
from typing import Optional

class SubtitleHelper:
    """VTT/SRT altyazı normalize edici ve formatlayıcı."""

    @staticmethod
    def normalize_subtitle_url(url: str, base_url: str = "") -> str:
        """Altyazı URL'sini tam URL'ye dönüştürür."""
        if url.startswith("http"):
            return url
        if url.startswith("//"):
            return f"https:{url}"
        if url.startswith("/"):
            return f"{base_url.rstrip('/')}{url}"
        return url

    @staticmethod
    def detect_format(url: str) -> Optional[str]:
        """URL'den altyazı formatını tespit eder."""
        if ".vtt" in url.lower():
            return "vtt"
        if ".srt" in url.lower():
            return "srt"
        if ".ass" in url.lower() or ".ssa" in url.lower():
            return "ass"
        return None
