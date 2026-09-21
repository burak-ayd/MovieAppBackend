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

    async def close_plugins(self):
        # Tüm eklentileri kapat
        for plugin in self.plugins.values():
            if isinstance(plugin, PluginBase):
                await plugin.close()

