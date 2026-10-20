"""Extract the parts of a FastAPI app that must survive the main.py split.

Used by both the offline stub check (scripts/refactor/stubcheck.py) and the
real-FastAPI test in CI (test_app_structure.py), so the same code produces the
snapshot and checks it.
"""

from __future__ import annotations

# Routes FastAPI adds on its own (docs / schema); they are not part of the app.
FASTAPI_DEFAULT_ENDPOINTS = {"openapi", "swagger_ui_html", "swagger_ui_redirect", "redoc_html"}
# Exception handlers FastAPI registers itself.
FASTAPI_DEFAULT_EXCEPTION_HANDLERS = {"HTTPException", "RequestValidationError", "WebSocketRequestValidationError"}


def _flatten(routes, prefix: str = ""):
    """Yield (prefix, route) in matching order.

    Newer FastAPI versions keep ``app.include_router(r)`` as one wrapper object
    (``_IncludedRouter``) instead of copying the routes; older ones copy them.
    Both match the included routes at the position of the include, so expand
    wrappers in place to get the same list either way.
    """
    for route in routes:
        inner = getattr(route, "original_router", None)
        if getattr(route, "endpoint", None) is None and inner is not None:
            yield from _flatten(inner.routes, prefix + (getattr(route, "prefix", "") or ""))
        else:
            yield prefix, route


def extract(app) -> dict:
    routes = []
    for prefix, route in _flatten(app.routes):
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None or getattr(endpoint, "__name__", "") in FASTAPI_DEFAULT_ENDPOINTS:
            continue
        routes.append([sorted(getattr(route, "methods", None) or []), prefix + route.path, endpoint.__name__])

    middleware = []
    for item in getattr(app, "user_middleware", []):
        options = getattr(item, "kwargs", None)
        if options is None:
            options = getattr(item, "options", {}) or {}
        dispatch = options.get("dispatch")
        middleware.append([getattr(item.cls, "__name__", str(item.cls)), getattr(dispatch, "__name__", None)])

    router = getattr(app, "router", app)
    return {
        "routes": routes,
        "middleware": middleware,
        "exception_handlers": sorted(
            name
            for name in (getattr(key, "__name__", str(key)) for key in getattr(app, "exception_handlers", {}))
            if name not in FASTAPI_DEFAULT_EXCEPTION_HANDLERS
        ),
        "startup": [getattr(fn, "__name__", str(fn)) for fn in getattr(router, "on_startup", [])],
        "shutdown": [getattr(fn, "__name__", str(fn)) for fn in getattr(router, "on_shutdown", [])],
    }


def describe_non_endpoint_routes(app) -> list:
    """Debug aid: routes that have no `endpoint` (nested routers, mounts)."""
    out = []
    for route in app.routes:
        if getattr(route, "endpoint", None) is None:
            out.append([
                type(route).__name__,
                getattr(route, "path", None),
                sorted(a for a in dir(route) if not a.startswith("_"))[:40],
            ])
    return out
