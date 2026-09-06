# Core Package

# Plugin
from .Plugin.PluginBase import PluginBase
from .Plugin.FlwBasePlugin import FlwBasePlugin
from .Plugin.PluginLoader import PluginLoader
from .Plugin.PluginManager import PluginManager
from .Plugin.PluginModels import (
    Episode,
    MainPageResult,
    MovieInfo,
    SearchResult,
    SeriesInfo,
    Subtitle as PluginSubtitle,
)

# Extractor
from .Extractor.ExtractorBase import ExtractorBase
from .Extractor.ExtractorLoader import ExtractorLoader
from .Extractor.ExtractorManager import ExtractorManager
from .Extractor.ExtractorModels import ExtractResult, Subtitle

# Media
from .Media.MediaHandler import MediaHandler
from .Media.MediaManager import MediaManager

# Helpers
from .Helpers.Cli import bellek_temizle, cikis_yap, debug_log, is_debug, konsol, set_debug
from .Helpers.FallbackClients import FallbackClients
from .Helpers.HTMLHelper import HTMLHelper
from .Helpers.Kontrol import MainUrlGuncelleyici
from .Helpers.MetadataHelper import MetadataHelper
from .Helpers.MethodCache import MethodCache
from .Helpers.Normalizer import Normalizer
from .Helpers.PlayabilityHelper import PlayabilityHelper
from .Helpers.SubtitleHelper import SubtitleHelper
from .Helpers.TitleHelper import TitleHelper

# Libs
from .Libs.Supabase import SupabaseManager
from .Libs.TMDB import TMDBClient

__all__ = [
    # Plugin
    "PluginBase",
    "FlwBasePlugin",
    "PluginLoader",
    "PluginManager",
    "Episode",
    "MainPageResult",
    "MovieInfo",
    "SearchResult",
    "SeriesInfo",
    "PluginSubtitle",
    # Extractor
    "ExtractorBase",
    "ExtractorLoader",
    "ExtractorManager",
    "ExtractResult",
    "Subtitle",
    # Media
    "MediaHandler",
    "MediaManager",
    # Helpers
    "konsol",
    "cikis_yap",
    "bellek_temizle",
    "is_debug",
    "set_debug",
    "debug_log",
    "HTMLHelper",
    "SubtitleHelper",
    "TitleHelper",
    "MetadataHelper",
    "Normalizer",
    "PlayabilityHelper",
    "MethodCache",
    "MainUrlGuncelleyici",
    "FallbackClients",
    # Libs
    "SupabaseManager",
    "TMDBClient",
]
