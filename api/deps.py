"""
API için merkezi bağımlılık yönetimi.
PluginManager, ExtractorManager gibi paylaşılan kaynakları sağlar.
"""

from Core.Plugin.PluginManager import PluginManager
from Core.Extractor.ExtractorManager import ExtractorManager
from Core.Helpers.Kontrol import MainUrlGuncelleyici

# ── Uygulama başlatıldığında bir kez oluşturulan tekil (singleton) nesneler ──

_plugin_manager: PluginManager | None = None
_extractor_manager: ExtractorManager | None = None


def get_plugin_manager() -> PluginManager:
    """Plugin yöneticisini döndürür (lazy singleton)."""
    global _plugin_manager
    if _plugin_manager is None:
        # URL'leri başlatmadan önce güncelle
        guncelleyici = MainUrlGuncelleyici()
        guncelleyici.guncelle()
        _plugin_manager = PluginManager()
    return _plugin_manager


def get_extractor_manager() -> ExtractorManager:
    """Extractor yöneticisini döndürür (lazy singleton)."""
    global _extractor_manager
    if _extractor_manager is None:
        _extractor_manager = ExtractorManager()
    return _extractor_manager
