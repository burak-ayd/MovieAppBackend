import re
from typing import Optional

class SubtitleHelper:
    """VTT/SRT altyazı normalize edici ve formatlayıcı."""

    LANGUAGE_MAP = {
        # Forced
        "forced": "Forced",
        "zorunlu": "Forced",
        "zorunlu altyazi": "Forced",
        "forced altyazi": "Forced",
        "forced sub": "Forced",
        # Turkish
        "turkish": "Turkish",
        "turkce": "Turkish",
        "turkce altyazi": "Turkish",
        "tr": "Turkish",
        "tur": "Turkish",
        # English
        "english": "English",
        "ingilizce": "English",
        "ingilizce altyazi": "English",
        "en": "English",
        "eng": "English",
        # French
        "french": "French",
        "fransizca": "French",
        "fr": "French",
        "fra": "French",
        "fre": "French",
        # German
        "german": "German",
        "almanca": "German",
        "de": "German",
        "ger": "German",
        "deu": "German",
        # Spanish
        "spanish": "Spanish",
        "ispanyolca": "Spanish",
        "ispanyolca altyazi": "Spanish",
        "es": "Spanish",
        "spa": "Spanish",
        # Portuguese
        "portuguese": "Portuguese",
        "portekizce": "Portuguese",
        "pt": "Portuguese",
        "por": "Portuguese",
        # Italian
        "italian": "Italian",
        "italyanca": "Italian",
        "it": "Italian",
        "ita": "Italian",
        # Russian
        "russian": "Russian",
        "rusca": "Russian",
        "ru": "Russian",
        "rus": "Russian",
        # Arabic
        "arabic": "Arabic",
        "arapca": "Arabic",
        "ar": "Arabic",
        "ara": "Arabic",
        # Persian
        "persian": "Persian",
        "farsca": "Persian",
        "fa": "Persian",
        "per": "Persian",
        # Korean
        "korean": "Korean",
        "korece": "Korean",
        "ko": "Korean",
        "kor": "Korean",
        # Japanese
        "japanese": "Japanese",
        "japonca": "Japanese",
        "ja": "Japanese",
        "jpn": "Japanese",
        # Chinese
        "chinese": "Chinese",
        "cince": "Chinese",
        "zh": "Chinese",
        "chi": "Chinese",
        "zho": "Chinese",
        # Azerbaijani
        "azerbaijani": "Azerbaijani",
        "azerbaycanca": "Azerbaijani",
        "az": "Azerbaijani",
        "aze": "Azerbaijani",
    }

    @staticmethod
    def _clean_str(text: str) -> str:
        """Türkçe karakterleri ve birleşik aksanları ASCII eşdeğerlerine normalize edip küçük harfe çevirir."""
        if not text:
            return ""
        t = text.replace("İ", "i").replace("I", "ı")
        t = t.lower()
        t = (
            t.replace("i\u0307", "i")
            .replace("ı", "i")
            .replace("ğ", "g")
            .replace("ü", "u")
            .replace("ş", "s")
            .replace("ö", "o")
            .replace("ç", "c")
        )
        return t.strip()

    @classmethod
    def normalize_name(cls, name: str) -> str:
        """Altyazı ismini Forced, Turkish, English gibi standart formatlara dönüştürür."""
        if not name:
            return "Turkish"

        raw = name.strip()
        cleaned = cls._clean_str(raw)

        # Forced / Zorunlu kontrolü (öncelikli)
        if "forced" in cleaned or "zorunlu" in cleaned:
            return "Forced"

        # Birebir harita eşleşmesi
        if cleaned in cls.LANGUAGE_MAP:
            return cls.LANGUAGE_MAP[cleaned]

        # Sondaki rakam / alt çizgi / tireleri temizle (örn. 'turkish2', 'turkce_1')
        base = re.sub(r"[\d_\-\s]+$", "", cleaned)
        if base in cls.LANGUAGE_MAP:
            return cls.LANGUAGE_MAP[base]

        # Alt dize eşleşmesi
        for key, val in cls.LANGUAGE_MAP.items():
            if len(key) > 2 and key in cleaned:
                return val

        return raw.title()

    LANGUAGE_CODE_MAP = {
        "Forced": "tr",
        "Turkish": "tr",
        "English": "en",
        "French": "fr",
        "German": "de",
        "Spanish": "es",
        "Portuguese": "pt",
        "Italian": "it",
        "Russian": "ru",
        "Arabic": "ar",
        "Persian": "fa",
        "Korean": "ko",
        "Japanese": "ja",
        "Chinese": "zh",
        "Azerbaijani": "az",
    }

    @classmethod
    def get_language_code(cls, name: str) -> str:
        """Normalize edilmiş veya ham altyazı isminden 2 harfli dil kodunu döner."""
        normalized = cls.normalize_name(name)
        return cls.LANGUAGE_CODE_MAP.get(normalized, "tr" if "turk" in (name or "").lower() else "und")

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

