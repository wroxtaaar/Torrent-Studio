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
export function webtorEmbedConfig(id: string, magnetUrl: string, title = ''): Record<string, unknown> | null {
  const magnet = String(magnetUrl || '').trim();
  if (!/^magnet:\?/i.test(magnet)) return null;
  return {
    id, magnet, width: '100%', lang: 'en',
    ...(title ? { title } : {}),
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
