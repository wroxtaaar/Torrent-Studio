/** Small, dependency-free helpers for the media player: resume position and keyboard shortcuts. */

const RESUME_PREFIX = 'ts-resume:';
const MIN_RESUME_S = 20;       // do not remember the first few seconds
const END_MARGIN_S = 30;       // a film that is (nearly) finished starts over next time

export interface StorageLike { getItem(key: string): string | null; setItem(key: string, value: string): void; removeItem(key: string): void }

function defaultStorage(): StorageLike | null {
  try { return typeof localStorage === 'undefined' ? null : localStorage; } catch { return null; }
}

export function resumeKey(file: { id?: string; name?: string } | null | undefined): string {
  const id = String(file?.id || file?.name || '');
  return id ? RESUME_PREFIX + id : '';
}

/** Where to continue from, or 0. */
export function loadResume(key: string, duration: number, storage: StorageLike | null = defaultStorage()): number {
  if (!key || !storage) return 0;
  try {
    const value = Number(storage.getItem(key));
    if (!Number.isFinite(value) || value < MIN_RESUME_S) return 0;
    if (duration > 0 && value > duration - END_MARGIN_S) return 0;
    return value;
  } catch { return 0; }
}

/** Remembers the position; clears it near the start or end. */
export function saveResume(key: string, time: number, duration: number, storage: StorageLike | null = defaultStorage()): void {
  if (!key || !storage || !Number.isFinite(time)) return;
  try {
    if (time < MIN_RESUME_S || (duration > 0 && time > duration - END_MARGIN_S)) storage.removeItem(key);
    else storage.setItem(key, String(Math.floor(time)));
  } catch { /* storage unavailable: resume is a convenience only */ }
}

export type PlayerShortcut =
  | { type: 'toggle' } | { type: 'seek'; seconds: number } | { type: 'volume'; delta: number }
  | { type: 'mute' } | { type: 'fullscreen' } | { type: 'jump'; fraction: number };

/** Maps a key press to a player action; null when the key is not a shortcut. */
export function shortcutForKey(key: string, modifiers: { ctrl?: boolean; meta?: boolean; alt?: boolean } = {}): PlayerShortcut | null {
  if (modifiers.ctrl || modifiers.meta || modifiers.alt) return null;
  switch (key) {
    case ' ': case 'k': case 'K': return { type: 'toggle' };
    case 'ArrowLeft': return { type: 'seek', seconds: -5 };
    case 'ArrowRight': return { type: 'seek', seconds: 5 };
    case 'j': case 'J': return { type: 'seek', seconds: -10 };
    case 'l': case 'L': return { type: 'seek', seconds: 10 };
    case 'ArrowUp': return { type: 'volume', delta: 0.1 };
    case 'ArrowDown': return { type: 'volume', delta: -0.1 };
    case 'm': case 'M': return { type: 'mute' };
    case 'f': case 'F': return { type: 'fullscreen' };
    default:
      if (/^[0-9]$/.test(key)) return { type: 'jump', fraction: Number(key) / 10 };
      return null;
  }
}

/** Double-tap zones: left third rewinds, right third skips ahead, the middle is fullscreen. */
export function tapZone(x: number, width: number): 'back' | 'forward' | 'center' {
  if (!(width > 0)) return 'center';
  const ratio = x / width;
  return ratio < 1 / 3 ? 'back' : ratio > 2 / 3 ? 'forward' : 'center';
}

const PREFS_KEY = 'ts-player-prefs';
export interface PlayerPrefs { volume: number; speed: number }

/** Volume and speed the viewer used last time (clamped), or the defaults. */
export function loadPrefs(storage: StorageLike | null = defaultStorage()): PlayerPrefs {
  const fallback: PlayerPrefs = { volume: 1, speed: 1 };
  if (!storage) return fallback;
  try {
    const raw = JSON.parse(storage.getItem(PREFS_KEY) || '{}');
    const volume = Number(raw?.volume);
    const speed = Number(raw?.speed);
    return {
      volume: Number.isFinite(volume) ? Math.min(1, Math.max(0, volume)) : 1,
      speed: Number.isFinite(speed) && speed >= 0.25 && speed <= 4 ? speed : 1,
    };
  } catch { return fallback; }
}

export function savePrefs(prefs: Partial<PlayerPrefs>, storage: StorageLike | null = defaultStorage()): void {
  if (!storage) return;
  try { storage.setItem(PREFS_KEY, JSON.stringify({ ...loadPrefs(storage), ...prefs })); } catch { /* convenience only */ }
}

/** How far ahead of the playhead the browser has already downloaded, as seconds (end of the buffered range holding `time`). */
export function bufferedEnd(ranges: { length: number; start(i: number): number; end(i: number): number } | null | undefined, time: number): number {
  if (!ranges) return 0;
  for (let index = 0; index < ranges.length; index += 1) {
    if (ranges.start(index) <= time + 0.25 && ranges.end(index) >= time) return ranges.end(index);
  }
  return 0;
}

/** Background for the seek bar: played (cyan), buffered (slate), rest (dark). */
export function seekGradient(time: number, buffered: number, duration: number): string {
  if (!(duration > 0)) return '';
  const played = Math.min(100, Math.max(0, (time / duration) * 100));
  const loaded = Math.min(100, Math.max(played, (buffered / duration) * 100));
  return `linear-gradient(to right, #22d3ee 0%, #22d3ee ${played}%, #64748b ${played}%, #64748b ${loaded}%, #1e293b ${loaded}%, #1e293b 100%)`;
}
