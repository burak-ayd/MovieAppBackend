# Core/Plugin Package

from .PluginBase import PluginBase
from .FlwBasePlugin import FlwBasePlugin
from .PluginLoader import PluginLoader
from .PluginManager import PluginManager
from .PluginModels import (
    Episode,
    MainPageResult,
    MovieInfo,
    SearchResult,
    SeriesInfo,
    Subtitle,
)

__all__ = [
    "PluginBase",
    "FlwBasePlugin",
    "PluginLoader",
    "PluginManager",
    "Episode",
    "MainPageResult",
    "MovieInfo",
    "SearchResult",
    "SeriesInfo",
    "Subtitle",
]
