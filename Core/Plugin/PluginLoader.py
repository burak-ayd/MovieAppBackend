from pathlib     import Path
import os, importlib.util, traceback, sys, types
from Core.Plugin.PluginBase import PluginBase
from Core.Helpers import konsol, cikis_yap


class PluginLoader:
    def __init__(self, plugins_dir: str):
        # Project root'u sys.path'e ekle
        self.project_root = Path(__file__).parent.parent.parent.resolve()
        if str(self.project_root) not in sys.path:
            sys.path.insert(0, str(self.project_root))

        # Yerel ve global eklenti dizinlerini ayarla
        self.local_plugins_dir  = Path(plugins_dir).resolve()
        self.global_plugins_dir = Path(__file__).parent.parent.parent / plugins_dir

        konsol.log(f"Local plugins dir: {self.local_plugins_dir}")
        konsol.log(f"Global plugins dir: {self.global_plugins_dir}")

        # Dizin kontrolü
        if not self.local_plugins_dir.exists() and not self.global_plugins_dir.exists():
            konsol.log("Eklenti dizinleri bulunamadı.")

    def load_all(self) -> dict[str, PluginBase]:
        plugins = {}

        # Global eklentileri yükle
        if self.global_plugins_dir.exists():
            plugins |= self._load_from_directory(self.global_plugins_dir)

        # Yerel eklentileri yükle
        if self.local_plugins_dir.exists():
            plugins |= self._load_from_directory(self.local_plugins_dir)

        if not plugins:
            konsol.print("[yellow][!] Yüklenecek bir Eklenti bulunamadı![/yellow]")

        return dict(sorted(plugins.items()))

    def _load_from_directory(self, directory: Path) -> dict[str, PluginBase]:
        plugins = {}

        # Dizindeki tüm .py dosyalarını tara
        for file in os.listdir(directory):
            if file.endswith(".py") and not file.startswith("__"):
                module_name = file[:-3]
                if plugin := self._load_plugin_as_package(directory, module_name):
                    plugins[module_name] = plugin

        return plugins

    def _load_plugin_as_package(self, directory: Path, module_name: str):
        """
        Plugin'i bir package altında yükler.
        Böylece relative import'lar (from ..Core) çalışır.
        """
        # Module-level PluginBase referansını sakla (variable shadowing önlemek için)
        BasePluginClass = PluginBase
        
        try:
            # Plugins package mock
            plugins_package_name = "Plugins"
            
            # __init__.py olmasa bile module olarak ekle
            if plugins_package_name not in sys.modules:
                plugins_pkg = types.ModuleType(plugins_package_name)
                plugins_pkg.__path__ = [str(directory)]
                plugins_pkg.__package__ = plugins_package_name
                sys.modules[plugins_package_name] = plugins_pkg

            # Core parent package mock
            if "Core" not in sys.modules:
                core_path = self.project_root / "Core"
                core_pkg = types.ModuleType("Core")
                core_pkg.__path__ = [str(core_path)]
                core_pkg.__package__ = "Core"
                sys.modules["Core"] = core_pkg

            # Core.Plugin parent package mock
            if "Core.Plugin" not in sys.modules:
                plugin_path = self.project_root / "Core" / "Plugin"
                core_plugin_pkg = types.ModuleType("Core.Plugin")
                core_plugin_pkg.__path__ = [str(plugin_path)]
                core_plugin_pkg.__package__ = "Core.Plugin"
                
                # PluginBase ve PluginModels'ı import et
                from .PluginBase import PluginBase as PB
                from .PluginModels import MainPageResult, SearchResult, MovieInfo
                from . import PluginModels
                
                core_plugin_pkg.PluginBase = PB
                core_plugin_pkg.PluginModels = PluginModels
                core_plugin_pkg.MainPageResult = MainPageResult
                core_plugin_pkg.SearchResult = SearchResult
                core_plugin_pkg.MovieInfo = MovieInfo
                
                sys.modules["Core.Plugin"] = core_plugin_pkg
                sys.modules["Core.Plugin.PluginBase"] = PB
                sys.modules["Core.Plugin.PluginModels"] = PluginModels

            # Plugin modülünü yükle
            plugin_path = directory / f"{module_name}.py"
            spec = importlib.util.spec_from_file_location(
                f"{plugins_package_name}.{module_name}",
                plugin_path,
                submodule_search_locations=[str(directory)]
            )
            
            if not spec or not spec.loader:
                raise ImportError(f"Spec oluşturulamadı: {module_name}")

            # Module oluştur ve package context ayarla
            module = importlib.util.module_from_spec(spec)
            module.__package__ = plugins_package_name
            module.__path__ = [str(directory)]
            
            # Modülü çalıştır
            spec.loader.exec_module(module)

            # PluginBase sınıfını bul (module-level referansı kullan)
            for attr in dir(module):
                obj = getattr(module, attr)
                if isinstance(obj, type) and issubclass(obj, BasePluginClass) and obj is not BasePluginClass:
                    return obj()

        except Exception as hata:
            konsol.print(f"[red][!] Eklenti yüklenirken hata oluştu: {module_name}\nHata: {hata}")
            konsol.print(f"[dim]{traceback.format_exc()}[/dim]")

        return None

    def _load_plugin(self, directory: Path, module_name: str):
        """Eski metod - kullanılmıyor."""
        return None