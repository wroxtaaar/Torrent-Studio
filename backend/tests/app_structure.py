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


def extract(app) -> dict:
    routes = []
    for route in app.routes:
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None or getattr(endpoint, "__name__", "") in FASTAPI_DEFAULT_ENDPOINTS:
            continue
        routes.append([sorted(getattr(route, "methods", None) or []), route.path, endpoint.__name__])

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
