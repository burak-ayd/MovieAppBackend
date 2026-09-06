# Core/Plugin/__init__.py
from .PluginLoader import PluginLoader
from .PluginManager import PluginManager
from .PluginModels import (
    SearchResult,
    Episode,
    SeriesInfo,
    MovieInfo,
    Subtitle,
    MainPageResult
)

__all__ = [
    'PluginLoader', 'PluginManager',
    'SearchResult', 'Episode', 'SeriesInfo', 'MovieInfo',
    'Subtitle',
    'MainPageResult'
]
