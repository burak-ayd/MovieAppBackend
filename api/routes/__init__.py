# API Routes Package
from .plugins import router as plugins_router
from .extractors import router as extractors_router
from .auth import router as auth_router
from .sync import router as sync_router

__all__ = ["plugins_router", "extractors_router", "auth_router", "sync_router"]
