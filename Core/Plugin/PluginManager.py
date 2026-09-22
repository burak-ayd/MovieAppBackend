import asyncio
from typing import List, Dict, Optional
from Core.Plugin.PluginBase import PluginBase
from Core.Plugin.PluginLoader import PluginLoader
from Core.Plugin.PluginModels import SearchResult

class PluginManager:
    def __init__(self, plugins_dir: str = "Plugins"):
        self.plugin_loader = PluginLoader(plugins_dir)
        self.plugins       = self.plugin_loader.load_all()


    def get_plugin_names(self):
        # Dizindeki tüm eklenti adlarını listeler ve sıralar
        return sorted(list(self.plugins.keys()))

    def select_plugin(self, plugin_name):
        if not plugin_name:
            return None
        if plugin_name in self.plugins:
            return self.plugins[plugin_name]
        lower_name = plugin_name.lower()
        for k, v in self.plugins.items():
            if k.lower() == lower_name or getattr(v, "name", "").lower() == lower_name:
                return v
        return None

    def find_plugin_by_url(self, url: str) -> Optional[PluginBase]:
        """Verilen URL'nin hangi eklentiye ait olduğunu tespit eder."""
        if not url:
            return None

        from urllib.parse import urlparse
        target_netloc = urlparse(url).netloc.lower().replace("www.", "")

        # 1. Domain / netloc eşleşmesi
        for plugin in self.plugins.values():
            p_netloc = urlparse(getattr(plugin, "main_url", "")).netloc.lower().replace("www.", "")
            if p_netloc and (p_netloc in target_netloc or target_netloc in p_netloc):
                return plugin

        # 2. İsim bazlı domain kontrolü (örn. hdfilmcehennemi veya dizibox)
        clean_target = target_netloc.replace("-", "").replace(".", "")
        for plugin in self.plugins.values():
            p_name = getattr(plugin, "name", "").lower().replace(" ", "").replace("_", "")
            if p_name and p_name in clean_target:
                return plugin

        return None

    async def close_plugins(self):
        # Tüm eklentileri kapat
        for plugin in self.plugins.values():
            if isinstance(plugin, PluginBase):
                await plugin.close()

