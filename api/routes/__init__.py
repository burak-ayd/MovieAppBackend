# API Routes Package
from .plugins import router as plugins_router
from .extractors import router as extractors_router

__all__ = ["plugins_router", "extractors_router"]
