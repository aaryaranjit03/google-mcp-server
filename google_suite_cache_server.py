# google_suite_server_cache.py
import asyncio
import json
import logging
import os
import sys
import importlib

from cache_helpers import get_or_fetch_and_cache, cache_invalidate, get_redis
from typing import Any

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("google-suite-cache-server")

# Load config
CONFIG_PATH = os.getenv("MCP_CONFIG_PATH", "mcp_endpoints.json")
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    MCP_CONFIG = json.load(f)

# Import your original server module (it should define `mcp`)
MODULE_NAME = os.getenv("ORIGINAL_MODULE", "google_suite_server")
if MODULE_NAME in sys.modules:
    del sys.modules[MODULE_NAME]
module = importlib.import_module(MODULE_NAME)

if not hasattr(module, "mcp"):
    raise RuntimeError(f"Imported module {MODULE_NAME} does not define 'mcp'")

mcp = getattr(module, "mcp")

# Register cache tools
@mcp.tool()
async def get_mcp_endpoint_info(endpoint_key: str) -> Any:
    """
    Return JSON for the configured endpoint_key using Redis cache and 5s timeout.
    """
    if "mcp_services" not in MCP_CONFIG:
        raise ValueError("mcp_endpoints.json missing mcp_services key")
    services = MCP_CONFIG["mcp_services"]
    if endpoint_key not in services:
        raise ValueError(f"Unknown endpoint key: {endpoint_key}")
    entry = services[endpoint_key]
    url = entry.get("url")
    ttl = int(entry.get("ttl_seconds", 300))
    cache_key = f"mcp:ep:{endpoint_key}"
    # fetch or return cached (throws on no-data & failure)
    data = await get_or_fetch_and_cache(cache_key, url, ttl=ttl, timeout=float(os.getenv("MCP_FETCH_TIMEOUT", "5.0")))
    return {"endpoint": endpoint_key, "cached": True, "data": data}

@mcp.tool()
async def invalidate_mcp_cache(endpoint_key: str) -> dict:
    cache_key = f"mcp:ep:{endpoint_key}"
    ok = await cache_invalidate(cache_key)
    return {"invalidated": bool(ok), "key": cache_key}

@mcp.tool()
async def list_cached_keys(pattern: str = "mcp:ep:*", limit: int = 100) -> list:
    r = get_redis()
    # use scan_iter to avoid blocking (async iterator)
    keys = []
    async for k in r.scan_iter(match=pattern, count=100):
        keys.append(k)
        if len(keys) >= limit:
            break
    return keys

# Now run the server (reuse the robust start strategy you used earlier).
def run_server():
    # attempt to call mcp.run with streamable-http; handle different SDK signatures
    run_callable = getattr(mcp, "run", None)
    if run_callable is None:
        raise RuntimeError("mcp.run not found on imported module")

    # Try common signatures
    tried = []
    try:
        # try keywords transport + mount_path
        return mcp.run(transport="streamable-http", mount_path="/mcp")
    except TypeError:
        pass
    try:
        return mcp.run("streamable-http", "/mcp")
    except TypeError:
        pass
    # fallback: try without transport (some SDKs return an ASGI app or have different API)
    try:
        return mcp.run("/mcp")
    except Exception as e:
        logger.exception("All mcp.run attempts failed: %s", e)
        raise

if __name__ == "__main__":
    run_server()
