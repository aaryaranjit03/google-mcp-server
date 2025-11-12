"""
google_suite_http_server.py (robust start)

This wrapper imports your original google_suite_server module (which should
define `mcp` as a FastMCP instance) and attempts multiple compatible ways
to expose it over Streamable HTTP regardless of small SDK differences.

Run:
    poetry run python google_suite_http_server.py
or
    poetry run python google_suite_http_server.py --host 0.0.0.0 --port 8000 --mount /mcp
"""

import argparse
import importlib
import inspect
import logging
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("google-suite-http-server")

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000
DEFAULT_MOUNT = "/mcp"


def import_module(module_name: str):
    logger.info("Importing module %s ...", module_name)
    if module_name in sys.modules:
        del sys.modules[module_name]
    try:
        mod = importlib.import_module(module_name)
    except Exception:
        logger.exception("Failed to import %s", module_name)
        raise
    logger.info("Imported module: %s", mod)
    return mod


def try_call_mcp_run(mcp, transport="streamable-http", host=DEFAULT_HOST, port=DEFAULT_PORT, mount_path=DEFAULT_MOUNT):
    """
    Try multiple plausible ways to call mcp.run depending on the installed SDK's signature.
    Returns True if the run call was performed (and should block), False if not attempted.
    """

    run_callable = getattr(mcp, "run", None)
    if run_callable is None:
        logger.info("mcp.run not present.")
        return False

    sig = None
    try:
        sig = inspect.signature(run_callable)
        logger.debug("mcp.run signature: %s", sig)
    except Exception as e:
        logger.warning("Could not inspect mcp.run signature: %s", e)

    attempts = []

    # 1) try keyword style: transport + mount_path (no host/port)
    attempts.append({"kwargs": {"transport": transport, "mount_path": mount_path}})

    # 2) try positional (transport, mount_path)
    attempts.append({"args": (transport, mount_path)})

    # 3) try single positional (mount_path)
    attempts.append({"args": (mount_path,)})

    # 4) try 'transport' only (older variants may accept transport)
    attempts.append({"args": (transport,)})

    # 5) try host/port as keywords (some variants do accept them)
    attempts.append({"kwargs": {"transport": transport, "host": host, "port": port, "mount_path": mount_path}})

    # Attempt all of them until one works
    for i, att in enumerate(attempts, start=1):
        try:
            if "kwargs" in att:
                logger.info("Trying mcp.run with kwargs attempt %d: %s", i, att["kwargs"])
                run_callable(**att["kwargs"])
            else:
                logger.info("Trying mcp.run with args attempt %d: %s", i, att["args"])
                run_callable(*att["args"])
            # If run_callable returns (blocking), we won't reach here until it exits.
            logger.info("mcp.run called successfully (attempt %d).", i)
            return True
        except TypeError as te:
            # signature mismatch; try next
            logger.debug("mcp.run attempt %d TypeError: %s", i, te)
            continue
        except SystemExit:
            # Some mcp.run implementations call sys.exit on failure -- re-raise
            raise
        except Exception as e:
            # If an attempt raised an exception other than TypeError, log and re-raise,
            # because it might indicate an attempt succeeded in starting and then errored.
            logger.exception("mcp.run attempt %d raised: %s", i, e)
            raise

    logger.warning("All mcp.run call attempts failed due to signature mismatch or errors.")
    return False


def try_get_asgi_from_mcp(mcp, mount_path=DEFAULT_MOUNT):
    """
    Some MCP SDKs provide an ASGI/Starlette app factory like mcp.http_app(path=...) or mcp.asgi_app
    Try several common names and signatures and return an ASGI app if found.
    """
    names_to_try = [
        ("http_app", (("path",), {"path": mount_path}), (("path",), {})),
        ("http_app", ((mount_path,),), ((),)),
        ("asgi_app", ((),), ((),)),
        ("http_app", ((),), ()),
        ("http_server", ((),), ()),
    ]

    for name, sigs, _dummy in names_to_try:
        if hasattr(mcp, name):
            attr = getattr(mcp, name)
            # If callable, try calling with signature variations
            if callable(attr):
                logger.info("Trying to get ASGI app via mcp.%s", name)
                try:
                    # try calling with named parameter first
                    try:
                        app = attr(path=mount_path)
                        logger.info("Obtained ASGI app from mcp.%s(path=...)", name)
                        return app
                    except TypeError:
                        pass
                    try:
                        app = attr(mount_path)
                        logger.info("Obtained ASGI app from mcp.%s(mount_path)", name)
                        return app
                    except Exception:
                        pass
                    # try without args
                    try:
                        app = attr()
                        logger.info("Obtained ASGI app from mcp.%s()", name)
                        return app
                    except Exception:
                        pass
                except Exception as e:
                    logger.debug("Calling mcp.%s raised: %s", name, e)
                    continue
            else:
                logger.info("mcp.%s is not callable but present; returning it", name)
                return attr
    logger.info("No ASGI app found on mcp via known attribute names.")
    return None


def serve_asgi_app_with_uvicorn(app, host=DEFAULT_HOST, port=DEFAULT_PORT):
    try:
        import uvicorn
    except Exception as e:
        logger.exception("uvicorn not installed: %s", e)
        raise RuntimeError("uvicorn is required to serve ASGI app. Install uvicorn.") from e

    logger.info("Serving ASGI app with uvicorn on %s:%s ...", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")


def try_embed_streamable_manager_in_fastapi(mcp, mount_path=DEFAULT_MOUNT, host=DEFAULT_HOST, port=DEFAULT_PORT):
    """
    As a last fallback, create a FastAPI app, create a StreamableHTTPSessionManager (if available),
    mount it, and run uvicorn. This covers SDK variants that use a session manager.
    """
    try:
        from fastapi import FastAPI
        import uvicorn
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    except Exception as e:
        logger.debug("FastAPI/StreamableHTTPSessionManager not available: %s", e)
        return False

    logger.info("Embedding StreamableHTTPSessionManager into FastAPI at %s", mount_path)
    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok", "time": time.time()}

    try:
        session_manager = StreamableHTTPSessionManager(mcp=mcp, mount_path=mount_path)
    except Exception as e:
        logger.exception("Failed to instantiate StreamableHTTPSessionManager: %s", e)
        return False

    # mount manager ASGI app if present, attempt common attribute names
    asgi_candidate = getattr(session_manager, "app", None) or getattr(session_manager, "get_asgi_app", None) or session_manager
    try:
        app.mount(mount_path, asgi_candidate)
    except Exception as e:
        logger.exception("Failed to mount session manager ASGI on FastAPI: %s", e)
        return False

    logger.info("Starting uvicorn for FastAPI-embedded streamable manager")
    uvicorn.run(app, host=host, port=port, log_level="info")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--module-name", default="google_suite_server", help="Module name of your original server file (without .py)")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--mount", default=DEFAULT_MOUNT)
    parser.add_argument("--no-embed-fastapi", action="store_true", help="Disable FastAPI embed fallback")
    args = parser.parse_args()

    module = import_module(args.module_name)

    # Call initialize_services if present (pre-warm tokens)
    if hasattr(module, "initialize_services"):
        try:
            logger.info("Calling initialize_services() from module to pre-warm credentials.")
            module.initialize_services()
        except Exception:
            logger.exception("initialize_services() raised an exception; continuing (lazy init may still work).")

    if not hasattr(module, "mcp"):
        logger.error("Module %s has no attribute 'mcp'. Ensure your original server defines `mcp = FastMCP(...)`.", args.module_name)
        sys.exit(2)

    mcp = getattr(module, "mcp")

    # 1) Try to call mcp.run in flexible ways
    try:
        started = try_call_mcp_run(mcp, transport="streamable-http", host=args.host, port=args.port, mount_path=args.mount)
        if started:
            logger.info("mcp.run completed (or is now running).")
            return
    except Exception as e:
        logger.exception("Attempt to call mcp.run raised an exception: %s", e)
        # If run raised an exception we don't immediately give up; try ASGI fallbacks below.

    # 2) Try to obtain an ASGI app from mcp and serve with uvicorn
    try:
        asgi = try_get_asgi_from_mcp(mcp, mount_path=args.mount)
        if asgi:
            logger.info("Serving ASGI app extracted from mcp via uvicorn.")
            serve_asgi_app_with_uvicorn(asgi, host=args.host, port=args.port)
            return
    except Exception as e:
        logger.exception("Failed to obtain/serve ASGI app from mcp: %s", e)

    # 3) Try to embed StreamableHTTPSessionManager in FastAPI (unless disabled)
    if not args.no_embed_fastapi:
        try:
            success = try_embed_streamable_manager_in_fastapi(mcp, mount_path=args.mount, host=args.host, port=args.port)
            if success:
                return
        except Exception as e:
            logger.exception("Embedding session manager in FastAPI failed: %s", e)

    logger.error("Could not start the MCP server via any supported method. Inspect logs above for details.")
    sys.exit(3)


if __name__ == "__main__":
    main()
