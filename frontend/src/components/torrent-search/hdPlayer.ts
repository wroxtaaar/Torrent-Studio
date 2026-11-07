/** Helpers for "Play HD": which device we are on and how to hand a stream link to VLC / MX Player. */

export type PlayerPlatform = 'android' | 'ios' | 'desktop';

export function platformFromUserAgent(userAgent: string, maxTouchPoints = 0): PlayerPlatform {
  if (/android/i.test(userAgent)) return 'android';
  // iPadOS reports a Mac user agent but has touch points.
  if (/iphone|ipad|ipod/i.test(userAgent) || (/macintosh/i.test(userAgent) && maxTouchPoints > 1)) return 'ios';
  return 'desktop';
}

export const currentPlatform = (): PlayerPlatform =>
  typeof navigator === 'undefined' ? 'desktop' : platformFromUserAgent(navigator.userAgent || '', navigator.maxTouchPoints || 0);

/** Android "intent:" link that opens the stream in a specific app (https URL only). */
export function androidIntent(url: string, androidPackage: string): string {
  const withoutScheme = url.replace(/^https:/i, '');
  return `intent:${withoutScheme}#Intent;scheme=https;package=${androidPackage};type=video/*;end`;
}

export const MX_PLAYER_PACKAGE = 'com.mxtech.videoplayer.ad';
export const VLC_PACKAGE = 'org.videolan.vlc';

/** Link that opens the stream in VLC, or '' when this platform has no reliable VLC link. */
export function vlcLink(url: string, platform: PlayerPlatform): string {
  if (!/^https:\/\//i.test(url)) return '';
  if (platform === 'android') return androidIntent(url, VLC_PACKAGE);
  if (platform === 'ios') return `vlc-x-callback://x-callback-url/stream?url=${encodeURIComponent(url)}`;
  return `vlc://${url}`;   // desktop: works when VLC registered its protocol handler; "Copy link" is the fallback
}

/** MX Player exists only on Android. */
export function mxPlayerLink(url: string, platform: PlayerPlatform): string {
  return platform === 'android' && /^https:\/\//i.test(url) ? androidIntent(url, MX_PLAYER_PACKAGE) : '';
}

/**
 * Chrome/Edge expose how many audio bytes the browser decoded; 0 after playback started means the video plays silently
 * (DTS / Dolby audio). Other browsers do not expose it, so unknown is treated as "has sound".
 */
export function playsSilently(video: Pick<HTMLVideoElement, 'currentTime' | 'muted'> & { webkitAudioDecodedByteCount?: number; mozHasAudio?: boolean }): boolean {
  if (video.muted || video.currentTime < 2) return false;
  if (typeof video.webkitAudioDecodedByteCount === 'number') return video.webkitAudioDecodedByteCount === 0;
  if (typeof video.mozHasAudio === 'boolean') return !video.mozHasAudio;
  return false;
}

export interface FileAudio { language: string; detail: string; label: string }

const LANGUAGES = 'hindi|english|tamil|telugu|malayalam|kannada|bengali|punjabi|marathi|gujarati|urdu|korean|japanese|chinese|mandarin|cantonese|spanish|french|german|italian|russian|portuguese|arabic|turkish|thai|multi|dual|org';
const AUDIO_PART = new RegExp(`^(${LANGUAGES})\\b[ ._-]*(.*)$`, 'i');

/**
 * The audio tracks a release name advertises, e.g. "[Hindi DDP 2.0 + English DTS-HDMA 5.1]" gives
 * Hindi (DDP 2.0) and English (DTS-HDMA 5.1). Only the name is read, so this is a hint, not the file's real track list.
 */
export function audioFromFilename(filename: string): FileAudio[] {
  for (const group of String(filename || '').match(/[\[(][^\])]*[\])]/g) || []) {
    const parts = group.slice(1, -1).split(/\s*\+\s*|\s*&\s*|\s*,\s*/).map(part => part.trim()).filter(Boolean);
    const tracks: FileAudio[] = [];
    for (const part of parts) {
      const match = part.match(AUDIO_PART);
      if (!match) { tracks.length = 0; break; }
      const language = match[1][0].toUpperCase() + match[1].slice(1).toLowerCase();
      const detail = match[2].replace(/\s+/g, ' ').trim();
      tracks.push({ language, detail, label: detail ? `${language} (${detail})` : language });
    }
    if (tracks.length > 0) return tracks;
  }
  return [];
}

export interface BrowserAudioTrack { id: string; label: string; language: string; enabled: boolean }

/** The audio tracks the browser itself exposes (Safari; Chrome and Firefox keep this behind a flag), or []. */
export function browserAudioTracks(video: unknown): BrowserAudioTrack[] {
  const list = (video as { audioTracks?: ArrayLike<BrowserAudioTrack> } | null)?.audioTracks;
  if (!list || typeof list.length !== 'number') return [];
  return Array.from({ length: list.length }, (_, index) => {
    const track = list[index];
    return { id: String(track.id ?? index), label: String(track.label || ''), language: String(track.language || ''), enabled: Boolean(track.enabled) };
  });
}
