import React from 'react';

/**
 * Staged poster loading shared by every movie card: cards first show the lightweight
 * (w185) thumbnail. The large (w780) version waits for page details and browser idle,
 * then loads at low priority so navigation and initial card content stay responsive.
 */
export let highQualityPostersReady = false;

export const pendingHighQualityPosters = new Set<HTMLImageElement>();

export const upgradedHighQualityPosters = new Set<HTMLImageElement>();

export let highQualityUpgradeScheduled = false;

/** Upgrades loading right now. Several run at once so a full page is not upgraded one poster at a time. */
export const highQualityUpgradesInFlight = new Set<HTMLImageElement>();

export const MAX_CONCURRENT_HIGH_QUALITY_UPGRADES = 4;

/** High-quality URLs that finished loading once: they are in the browser cache, so revisits reuse them at once. */
export const loadedHighQualityUrls = new Set<string>();

/** Quiet time (no tap/scroll/key) before upgrades start. */
export const POSTER_UPGRADE_IDLE_MS = 500;

export let highQualityUpgradeGeneration = 0;

export let highQualityIdleHandle: number | null = null;

export let highQualityFallbackTimer: number | null = null;

export let lastPosterUserActivity = Date.now();

if (typeof document !== 'undefined') {
  const notePosterUserActivity = () => {
    lastPosterUserActivity = Date.now();
  };
  document.addEventListener('pointerdown', notePosterUserActivity, { passive: true });
  document.addEventListener('keydown', notePosterUserActivity);
  document.addEventListener('scroll', notePosterUserActivity, { passive: true });
  document.addEventListener('touchstart', notePosterUserActivity, { passive: true });
}

/**
 * Direct IMDb/Amazon and Metahub poster links can also be requested small first.
 * Amazon: '..._V1_.jpg' is the full-size original; '_V1_UX185_.jpg' / '_V1_UX500_.jpg' are resized.
 * Metahub: '/poster/small/' vs '/poster/medium/'. Returns null for any other host or shape.
 */
export function resizeKnownPosterHost(value: string, quality: 'low' | 'high'): string | null {
  const url = String(value || '').trim();
  if (!url) return null;
  try {
    const parsed = new URL(url, window.location.origin);
    const host = parsed.hostname.toLowerCase();
    if (host.endsWith('media-amazon.com')) {
      const marker = '._V1_';
      const at = parsed.pathname.indexOf(marker);
      if (at < 0) return null;
      parsed.pathname = parsed.pathname.slice(0, at) + marker + (quality === 'low' ? 'UX185_' : 'UX500_') + '.jpg';
      return parsed.toString();
    }
    if (host === 'images.metahub.space' && /\/poster\/(?:small|medium)\//.test(parsed.pathname)) {
      parsed.pathname = parsed.pathname.replace(/\/poster\/(?:small|medium)\//, '/poster/' + (quality === 'low' ? 'small' : 'medium') + '/');
      return parsed.toString();
    }
  } catch {
    return null;
  }
  return null;
}

export function normalizeLowQualityPosterUrl(value: string): string {
  const url = String(value || '').trim();
  if (!url) return '';
  try {
    const parsed = new URL(url, window.location.origin);
    // Catalogue poster URLs are resolved by the backend. Explicitly request the
    // small same-origin image variant instead of allowing a redirect to w500.
    if (parsed.pathname.replace(/\/+$/, '') === '/api/poster') {
      parsed.searchParams.set('size', 'w185');
    } else if (parsed.hostname === 'image.tmdb.org') {
      parsed.pathname = parsed.pathname.replace(
        /\/t\/p\/(?:original|w780|w500|w342|w300|w200|w185|w154|w92)\//,
        '/t/p/w185/',
      );
    } else {
      const resized = resizeKnownPosterHost(url, 'low');
      if (resized) return resized;
    }
    return parsed.toString();
  } catch {
    return url;
  }
}

export function cancelHighQualityUpgradeSchedule(): void {
  const idleWindow = window as Window & {
    cancelIdleCallback?: (handle: number) => void;
  };
  if (highQualityIdleHandle !== null) {
    idleWindow.cancelIdleCallback?.(highQualityIdleHandle);
    highQualityIdleHandle = null;
  }
  if (highQualityFallbackTimer !== null) {
    window.clearTimeout(highQualityFallbackTimer);
    highQualityFallbackTimer = null;
  }
  highQualityUpgradeScheduled = false;
}

export function restoreLowQualityPoster(image: HTMLImageElement): void {
  if (!image.isConnected || image.dataset.highQualityTried !== 'true') return;
  // A finished high-quality poster is already cached by the browser: keep it instead of
  // downgrading it and loading it again after the next navigation.
  if (image.complete && image.naturalWidth > 0 && loadedHighQualityUrls.has(image.currentSrc || image.src)) return;
  const lowQualityUrl = normalizeLowQualityPosterUrl(image.currentSrc || image.src);
  image.dataset.highQualityTried = '';
  image.dataset.highQualityFailed = '';
  image.dataset.posterQuality = 'low-retrying';
  image.fetchPriority = 'high';
  image.loading = 'eager';
  if (lowQualityUrl && image.src !== lowQualityUrl) image.src = lowQualityUrl;
}

/** The high-quality URL this poster would be upgraded to, or null when it has none. */
export function highQualityVariant(current: string): string | null {
  try {
    const parsed = new URL(current, window.location.origin);
    if (parsed.pathname.replace(/\/+$/, '') === '/api/poster') {
      parsed.searchParams.set('size', 'w780');
      return parsed.toString();
    }
  } catch {
    return null;
  }
  const resizedHigh = resizeKnownPosterHost(current, 'high');
  if (resizedHigh && resizeKnownPosterHost(current, 'low') === current) return resizedHigh;
  if (current.includes('image.tmdb.org') && /\/t\/p\/w185\//.test(current)) return current.replace('/t/p/w185/', '/t/p/w780/');
  return null;
}

export function upgradeToHighQualityPoster(image: HTMLImageElement): boolean {
  if (
    !image.isConnected ||
    image.dataset.highQualityTried === 'true' ||
    image.dataset.highQualityFailed === 'true'
  ) return false;
  const current = image.src || image.currentSrc;
  try {
    const parsed = new URL(current, window.location.origin);
    if (parsed.pathname.replace(/\/+$/, '') === '/api/poster') {
      parsed.searchParams.set('size', 'w780');
      const highQualityUrl = parsed.toString();
      if (highQualityUrl === current) return false;
      image.fetchPriority = 'low';
      image.loading = 'lazy';
      image.dataset.highQualityTried = 'true';
      image.dataset.posterQuality = 'high-pending';
      image.src = highQualityUrl;
      upgradedHighQualityPosters.add(image);
      highQualityUpgradesInFlight.add(image);
      return true;
    }
  } catch {
    // Fall through to the direct TMDB URL handling below.
  }
  const resizedHigh = resizeKnownPosterHost(current, 'high');
  if (resizedHigh && resizedHigh !== current && resizeKnownPosterHost(current, 'low') === current) {
    image.fetchPriority = 'low';
    image.loading = 'lazy';
    image.dataset.highQualityTried = 'true';
    image.dataset.posterQuality = 'high-pending';
    image.src = resizedHigh;
    upgradedHighQualityPosters.add(image);
    highQualityUpgradesInFlight.add(image);
    return true;
  }
  if (!current.includes('image.tmdb.org') || !/\/t\/p\/w185\//.test(current)) return false;
  image.fetchPriority = 'low';
  image.loading = 'lazy';
  image.dataset.highQualityTried = 'true';
  image.dataset.posterQuality = 'high-pending';
  image.src = current.replace('/t/p/w185/', '/t/p/w780/');
  upgradedHighQualityPosters.add(image);
  highQualityUpgradesInFlight.add(image);
  return true;
}

export function scheduleHighQualityPosterUpgrades(): void {
  if (
    !highQualityPostersReady ||
    highQualityUpgradeScheduled ||
    highQualityUpgradesInFlight.size >= MAX_CONCURRENT_HIGH_QUALITY_UPGRADES ||
    pendingHighQualityPosters.size === 0
  ) return;
  highQualityUpgradeScheduled = true;
  const generation = highQualityUpgradeGeneration;

  const run = () => {
    highQualityIdleHandle = null;
    highQualityFallbackTimer = null;
    highQualityUpgradeScheduled = false;
    if (
      generation !== highQualityUpgradeGeneration ||
      !highQualityPostersReady ||
      highQualityUpgradesInFlight.size >= MAX_CONCURRENT_HIGH_QUALITY_UPGRADES ||
      pendingHighQualityPosters.size === 0
    ) return;
    if (Date.now() - lastPosterUserActivity < POSTER_UPGRADE_IDLE_MS) {
      scheduleHighQualityPosterUpgrades();
      return;
    }

    const images = [...pendingHighQualityPosters].filter(image => image.isConnected);
    images.sort((a, b) => {
      const visible = (image: HTMLImageElement) => {
        const rect = image.getBoundingClientRect();
        return rect.bottom > 0 && rect.top < window.innerHeight && rect.right > 0 && rect.left < window.innerWidth;
      };
      return Number(visible(b)) - Number(visible(a));
    });

    for (const image of images) {
      if (highQualityUpgradesInFlight.size >= MAX_CONCURRENT_HIGH_QUALITY_UPGRADES) break;
      pendingHighQualityPosters.delete(image);
      upgradeToHighQualityPoster(image);
    }
  };

  const idleWindow = window as Window & {
    requestIdleCallback?: (callback: () => void, options?: { timeout: number }) => number;
  };
  if (idleWindow.requestIdleCallback) {
    highQualityIdleHandle = idleWindow.requestIdleCallback(run, { timeout: 1000 });
  } else {
    highQualityFallbackTimer = window.setTimeout(run, 600);
  }
}

export function requestHighQualityPoster(image: HTMLImageElement): void {
  if (image.dataset.highQualityTried === 'true') {
    // This is the load (or error) event of the upgraded image: free its slot and remember
    // the URL so the next visit to this poster can use the cached high-quality image at once.
    highQualityUpgradesInFlight.delete(image);
    if (image.complete && image.naturalWidth > 0) {
      const loaded = image.currentSrc || image.src;
      if (loaded) loadedHighQualityUrls.add(loaded);
    }
    scheduleHighQualityPosterUpgrades();
    return;
  }
  // Seen before in high quality: swap straight to the cached image, no idle wait or queue.
  const known = highQualityVariant(image.src || image.currentSrc);
  if (known && loadedHighQualityUrls.has(known) && image.dataset.highQualityFailed !== 'true') {
    image.dataset.highQualityTried = 'true';
    image.dataset.posterQuality = 'high-pending';
    upgradedHighQualityPosters.add(image);
    image.src = known;
    return;
  }
  pendingHighQualityPosters.add(image);
  if (image.dataset.posterQuality === 'low-loaded' || image.complete) scheduleHighQualityPosterUpgrades();
}

/** Pause and reset upgrades on navigation; resume only after the page details settle. */
export function setHighQualityPostersReady(ready: boolean): void {
  if (!ready) {
    highQualityUpgradeGeneration += 1;
    cancelHighQualityUpgradeSchedule();
    highQualityUpgradesInFlight.clear();
    pendingHighQualityPosters.clear();
    for (const image of upgradedHighQualityPosters) {
      restoreLowQualityPoster(image);
    }
    upgradedHighQualityPosters.clear();
    for (const image of document.querySelectorAll<HTMLImageElement>('img[data-movie-poster-stage="true"]')) {
      image.dataset.highQualityFailed = '';
    }
  }
  highQualityPostersReady = ready;
  if (!ready) {
    return;
  }
  scheduleHighQualityPosterUpgrades();
}

export type PosterEventHandler = (event: React.SyntheticEvent<HTMLImageElement>) => void;
