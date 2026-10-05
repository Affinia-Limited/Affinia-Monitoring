"""Small cache abstraction: Redis when ``REDIS_URL`` is set, otherwise in-process TTL.

Only non-sensitive monitoring data (metric series, resource graph results, health
snapshots) is cached. Tokens and secrets are never cached here.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class Cache(Protocol):
    async def get(self, key: str) -> Any | None: ...
    async def set(self, key: str, value: Any, ttl: int) -> None: ...
    async def delete_prefix(self, prefix: str) -> None: ...
    async def incr(self, key: str, ttl: int) -> int: ...
    async def ping(self) -> bool: ...


class MemoryCache:
    def __init__(self, max_items: int = 10_000):
        self._items: dict[str, tuple[float, Any]] = {}
        self._max = max_items

    async def get(self, key: str) -> Any | None:
        entry = self._items.get(key)
        if entry is None:
            return None
        expires, value = entry
        if expires < time.monotonic():
            self._items.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: Any, ttl: int) -> None:
        if len(self._items) >= self._max:
            now = time.monotonic()
            for k in [k for k, (exp, _) in self._items.items() if exp < now]:
                self._items.pop(k, None)
            if len(self._items) >= self._max:
                self._items.pop(next(iter(self._items)))
        self._items[key] = (time.monotonic() + ttl, value)

    async def delete_prefix(self, prefix: str) -> None:
        for k in [k for k in self._items if k.startswith(prefix)]:
            self._items.pop(k, None)

    async def incr(self, key: str, ttl: int) -> int:
        current = await self.get(key)
        value = int(current or 0) + 1
        if current is None:
            await self.set(key, value, ttl)
        else:
            self._items[key] = (self._items[key][0], value)
        return value

    async def ping(self) -> bool:
        return True


class RedisCache:
    def __init__(self, url: str):
        from redis.asyncio import Redis

        self._redis = Redis.from_url(url, decode_responses=True, socket_timeout=2)

    async def get(self, key: str) -> Any | None:
        try:
            raw = await self._redis.get(key)
        except Exception:  # cache failures must never break requests
            logger.warning("cache_get_failed")
            return None
        return json.loads(raw) if raw is not None else None

    async def set(self, key: str, value: Any, ttl: int) -> None:
        try:
            await self._redis.set(key, json.dumps(value, default=str), ex=ttl)
        except Exception:
            logger.warning("cache_set_failed")

    async def delete_prefix(self, prefix: str) -> None:
        try:
            async for k in self._redis.scan_iter(match=f"{prefix}*", count=500):
                await self._redis.delete(k)
        except Exception:
            logger.warning("cache_delete_failed")

    async def incr(self, key: str, ttl: int) -> int:
        try:
            pipe = self._redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, ttl, nx=True)
            value, _ = await pipe.execute()
            return int(value)
        except Exception:
            logger.warning("cache_incr_failed")
            return 0

    async def ping(self) -> bool:
        try:
            return bool(await self._redis.ping())
        except Exception:
            return False


def cache_key(namespace: str, *parts: Any) -> str:
    digest = hashlib.sha256(json.dumps(parts, default=str, sort_keys=True).encode()).hexdigest()[:32]
    return f"amp:{namespace}:{digest}"


_cache: Cache | None = None


def get_cache() -> Cache:
    global _cache
    if _cache is None:
        from app.core.config import get_settings

        url = get_settings().redis_url
        _cache = RedisCache(url) if url else MemoryCache()
    return _cache


def set_cache(cache: Cache | None) -> None:
    global _cache
    _cache = cache
