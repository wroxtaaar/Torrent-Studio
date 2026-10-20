// Home is a VPS-only all-in-one deployment: the browser talks directly
// to the same origin on the Oracle VPS for both the React UI and FastAPI.
// Keep VITE_API_URL only as an optional override for local development.
const configuredApiBase = String(import.meta.env.VITE_API_URL || '').trim();
export const API_BASE = (
  configuredApiBase ||
  (typeof window !== 'undefined' ? window.location.origin : 'http://127.0.0.1:10000')
).replace(/\/+$/, '');

export const makeSeedrError = (data: any, body: string, status: number, fallback: string) => {
  const error = new Error(
    data?.error ||
    data?.message ||
    data?.detail ||
    body ||
    fallback
  ) as Error & { code?: string; status?: number };
  error.code = typeof data?.code === 'string' ? data.code : undefined;
  error.status = status;
  return error;
};

// CSRF token handed out by /api/seedr/session; sent with every state-changing /api/* request.
let seedrCsrfToken = '';
export const getSeedrCsrfToken = () => seedrCsrfToken;
export const setSeedrCsrfToken = (token: string) => {
  seedrCsrfToken = token;
};

export const apiFetch = (input: RequestInfo | URL, init?: RequestInit) => {
  const value = String(input);
  const url = value.startsWith('/') ? API_BASE + value : value;
  const method = String(init?.method || 'GET').toUpperCase();
  // Some callers pass an absolute URL (API_BASE + '/api/...'); normalise to a
  // path so the CSRF header is attached to every state-changing API request.
  const path = value.startsWith('/')
    ? value
    : API_BASE && value.startsWith(API_BASE)
      ? value.slice(API_BASE.length)
      : value;
  const isApiMutation =
    path.startsWith('/api/') &&
    !['GET', 'HEAD', 'OPTIONS'].includes(method);

  const headers = new Headers(init?.headers || undefined);
  if (isApiMutation && seedrCsrfToken) {
    headers.set('X-Torrent-Studio-CSRF', seedrCsrfToken);
  }

  return fetch(url, {
    ...init,
    headers,
    credentials: 'include',
  });
};
