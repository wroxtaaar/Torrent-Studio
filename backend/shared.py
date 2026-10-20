"""Moved out of main.py (see docs/main-split-plan.md)."""

import contextvars

# Live torrent-provider searches are allowed only inside the explicit manual-search route.
_MANUAL_TORRENT_SEARCH = contextvars.ContextVar("manual_torrent_search", default=False)
_REGIONAL_MOVIE_CATALOGUE_FORCE_REFRESH = contextvars.ContextVar(
    "regional_movie_catalogue_force_refresh",
    default=False,
)
_REGIONAL_MOVIE_SOURCE_FORCE_REFRESH = contextvars.ContextVar(
    "regional_movie_source_force_refresh",
    default=False,
)
_REGIONAL_MOVIE_SOURCE_REFRESHED_KEYS = contextvars.ContextVar(
    "regional_movie_source_refreshed_keys",
    default=None,
)


_seedr_request_token: contextvars.ContextVar[str] = contextvars.ContextVar("seedr_request_token", default="")
_seedr_request_session_id: contextvars.ContextVar[str] = contextvars.ContextVar("seedr_request_session_id", default="")


class SeedrError(Exception):
    def __init__(self, code: str, status_code: int, detail: str):
        self.code = code
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)
