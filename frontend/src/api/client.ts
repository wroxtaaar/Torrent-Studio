// Public API client. The code lives in focused modules; this file keeps the original
// import surface (`api`, `API_BASE` and all response types) for the rest of the app.
import { searchApi } from './search.ts';
import { torrentsApi } from './torrents.ts';
import { seedrApi } from './seedr.ts';
import { compatApi } from './compat.ts';
export { API_BASE } from './http.ts';
export * from './types.ts';

export const api = {
  ...searchApi,
  ...torrentsApi,
  ...seedrApi,
  ...compatApi,
};
