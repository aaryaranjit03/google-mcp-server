# cache_helpers.py
import os
import json
import logging
from typing import Any, Optional

import httpx
import redis.asyncio as aioredis

logger = logging.getLogger("mcp-cache")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CACHE_TTL_DEFAULT = int(os.getenv("MCP_CACHE_TTL", "300"))  # seconds
FETCH_TIMEOUT = float(os.getenv("MCP_FETCH_TIMEOUT", "5.0"))  # seconds

_redis_client: Optional[aioredis.Redis] = None


def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
    return _redis_client


async def fetch_json_with_timeout(url: str, timeout: float = FETCH_TIMEOUT) -> Any:
    """
    Async fetch JSON from url with httpx and a timeout (raises on non-200 or parse error).
    """
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


async def cache_get(key: str) -> Optional[Any]:
    r = get_redis()
    raw = await r.get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return raw


async def cache_set(key: str, value: Any, ttl: int = CACHE_TTL_DEFAULT) -> None:
    r = get_redis()
    raw = json.dumps(value)
    await r.setex(key, ttl, raw)


async def cache_invalidate(key: str) -> bool:
    r = get_redis()
    deleted = await r.delete(key)
    return deleted > 0


async def get_or_fetch_and_cache(
    key: str,
    url: str,
    ttl: int = CACHE_TTL_DEFAULT,
    timeout: float = FETCH_TIMEOUT,
    allow_stale_on_timeout: bool = True,
) -> Any:
    """
    Try cache -> if miss, fetch with timeout -> store cache -> return JSON.
    On timeout or fetch error, return stale cache if available (if allow_stale_on_timeout).
    Raises if no cache and fetch fails.
    """
    # 1) cached
    cached = await cache_get(key)
    if cached is not None:
        logger.debug("cache hit: %s", key)
        return cached

    logger.debug("cache miss: %s -> fetching %s", key, url)
    try:
        data = await fetch_json_with_timeout(url, timeout=timeout)
    except httpx.TimeoutException as te:
        logger.warning("timeout fetching %s: %s", url, te)
        if allow_stale_on_timeout:
            stale = await cache_get(key)
            if stale is not None:
                logger.info("returning stale cache for %s after timeout", key)
                return stale
        raise
    except Exception as e:
        logger.exception("error fetching %s: %s", url, e)
        if allow_stale_on_timeout:
            stale = await cache_get(key)
            if stale is not None:
                return stale
        raise

    # store
    await cache_set(key, data, ttl=ttl)
    return data
