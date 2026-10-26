// Titles whose NexStream playback does not work are reported to the server (it keeps them in a shared
// list used when the cache is rebuilt) and remembered here so this browser stops offering Play at once.
import { apiFetch } from '../../api/http.ts';

const STORAGE_KEY = 'nexstream_reported_v1';
const FORGIVE_AFTER_MS = 14 * 24 * 60 * 60 * 1000;

function readReported(): Record<string, number> {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || '{}');
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

export function isNexStreamReported(tmdbId: number | string | undefined | null): boolean {
  const at = readReported()[String(tmdbId)];
  return typeof at === 'number' && Date.now() - at < FORGIVE_AFTER_MS;
}

export function reportNexStreamFailure(
  item: { tmdbId: number; title: string; year?: number | string | null },
  reason: 'resolve_failed' | 'player_not_working',
): void {
  if (!Number.isInteger(item.tmdbId) || item.tmdbId <= 0) return;
  const already = isNexStreamReported(item.tmdbId);
  try {
    const reported = readReported();
    reported[String(item.tmdbId)] = Date.now();
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(reported));
  } catch { /* storage unavailable: the server report still goes out */ }
  if (already) return;
  const year = Number(item.year);
  void apiFetch('/api/nexstream/report', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      tmdbId: item.tmdbId,
      title: String(item.title || '').slice(0, 200),
      year: Number.isInteger(year) && year >= 1870 && year <= 2100 ? year : null,
      reason,
    }),
  }).catch(() => { /* best effort */ });
}
