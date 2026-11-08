export const WEBTOR_URL = 'https://webtor.io/';

/** Copy text without awaiting, so the caller stays inside the user's click (popup blockers). */
export function copyTextNow(text: string): boolean {
  try {
    const area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.style.cssText = 'position:fixed;top:-1000px;opacity:0';
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand('copy');
    area.remove();
    if (ok) return true;
  } catch { /* fall through to the async API */ }
  try { void navigator.clipboard?.writeText(text); return Boolean(navigator.clipboard); } catch { return false; }
}

/** Copy the magnet, then open Webtor in a new tab where the user pastes it to stream or download. */
export function copyMagnetAndOpenWebtor(magnetUrl: string): boolean {
  const copied = copyTextNow(magnetUrl);
  window.open(WEBTOR_URL, '_blank', 'noopener,noreferrer');
  return copied;
}

export const WEBTOR_SDK_URL = 'https://cdn.jsdelivr.net/npm/@webtor/embed-sdk-js/dist/index.min.js';

/** Config for Webtor's embed SDK (MIT). Only magnet links are accepted; anything else returns null. */
export function webtorEmbedConfig(id: string, magnetUrl: string, title = '', path = ''): Record<string, unknown> | null {
  const magnet = String(magnetUrl || '').trim();
  if (!/^magnet:\?/i.test(magnet)) return null;
  return {
    id, magnet, width: '100%', height: '640px', lang: 'en',
    ...(title ? { title } : {}),
    ...(path ? { path } : {}),
    features: { chromecast: false, embed: false },
  };
}

/** Loads the SDK once; later calls reuse the same promise. Rejects when the script cannot load (blocked / offline). */
let sdkPromise: Promise<void> | null = null;
export function loadWebtorSdk(): Promise<void> {
  if (sdkPromise) return sdkPromise;
  sdkPromise = new Promise<void>((resolve, reject) => {
    const script = document.createElement('script');
    script.src = WEBTOR_SDK_URL;
    script.async = true;
    script.charset = 'utf-8';
    script.onload = () => resolve();
    script.onerror = () => { sdkPromise = null; script.remove(); reject(new Error('Webtor player could not be loaded')); };
    document.head.appendChild(script);
  });
  return sdkPromise;
}

const BASE32 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';

/** The 40-character hex info hash of a magnet link (hex or base32 `btih`), or '' when there is none. */
export function magnetInfoHash(magnetUrl: string): string {
  const match = String(magnetUrl || '').match(/[?&]xt=urn:btih:([A-Za-z0-9]+)/i);
  if (!match) return '';
  const value = match[1];
  if (/^[0-9a-fA-F]{40}$/.test(value)) return value.toLowerCase();
  if (/^[A-Za-z2-7]{32}$/.test(value)) {
    let bits = '';
    for (const char of value.toUpperCase()) bits += BASE32.indexOf(char).toString(2).padStart(5, '0');
    let hex = '';
    for (let index = 0; index + 4 <= bits.length && hex.length < 40; index += 4) hex += parseInt(bits.slice(index, index + 4), 2).toString(16);
    return hex.slice(0, 40);
  }
  return '';
}

/** Webtor's page for a torrent (Stream and Download buttons live there), or '' for a magnet without a hash. */
export function webtorTorrentPageUrl(magnetUrl: string): string {
  const hash = magnetInfoHash(magnetUrl);
  return hash ? `${WEBTOR_URL}${hash}` : '';
}

/** Copies the magnet (in case Webtor does not know the torrent yet) and opens its torrent page where Download is one tap. */
export function openWebtorDownload(magnetUrl: string): { copied: boolean; opened: boolean } {
  const copied = copyTextNow(magnetUrl);
  const page = webtorTorrentPageUrl(magnetUrl);
  window.open(page || WEBTOR_URL, '_blank', 'noopener,noreferrer');
  return { copied, opened: Boolean(page) };
}
