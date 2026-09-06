import asyncio
from functools import wraps
from typing import Any, Dict, Tuple
import time

class MethodCache:
    """TTL destekli in-memory async cache dekoratörü."""

    def __init__(self, ttl: int = 300):
        self.ttl = ttl
        self._cache: Dict[str, Tuple[Any, float]] = {}

    def __call__(self, func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            key = f"{func.__name__}:{args[1:]}:{kwargs}"
            if key in self._cache:
                value, timestamp = self._cache[key]
                if time.time() - timestamp < self.ttl:
                    return value
                del self._cache[key]

            result = await func(*args, **kwargs)
            self._cache[key] = (result, time.time())
            return result

        return wrapper
