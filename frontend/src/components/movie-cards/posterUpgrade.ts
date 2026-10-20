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

export let highQualityUpgradeInFlight = false;

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
  const lowQualityUrl = normalizeLowQualityPosterUrl(image.currentSrc || image.src);
  image.dataset.highQualityTried = '';
  image.dataset.highQualityFailed = '';
  image.dataset.posterQuality = 'low-retrying';
  image.fetchPriority = 'high';
  image.loading = 'eager';
  if (lowQualityUrl && image.src !== lowQualityUrl) image.src = lowQualityUrl;
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
      highQualityUpgradeInFlight = true;
      return true;
    }
  } catch {
    // Fall through to the direct TMDB URL handling below.
  }
  if (!current.includes('image.tmdb.org') || !/\/t\/p\/w185\//.test(current)) return false;
  image.fetchPriority = 'low';
  image.loading = 'lazy';
  image.dataset.highQualityTried = 'true';
  image.dataset.posterQuality = 'high-pending';
  image.src = current.replace('/t/p/w185/', '/t/p/w780/');
  upgradedHighQualityPosters.add(image);
  highQualityUpgradeInFlight = true;
  return true;
}

export function scheduleHighQualityPosterUpgrades(): void {
  if (
    !highQualityPostersReady ||
    highQualityUpgradeScheduled ||
    highQualityUpgradeInFlight ||
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
      highQualityUpgradeInFlight ||
      pendingHighQualityPosters.size === 0
    ) return;
    if (Date.now() - lastPosterUserActivity < 1800) {
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
      pendingHighQualityPosters.delete(image);
      if (upgradeToHighQualityPoster(image)) return;
    }
  };

  const idleWindow = window as Window & {
    requestIdleCallback?: (callback: () => void, options?: { timeout: number }) => number;
  };
  if (idleWindow.requestIdleCallback) {
    highQualityIdleHandle = idleWindow.requestIdleCallback(run, { timeout: 5000 });
  } else {
    highQualityFallbackTimer = window.setTimeout(run, 2500);
  }
}

export function requestHighQualityPoster(image: HTMLImageElement): void {
  if (image.dataset.highQualityTried === 'true') {
    if (upgradedHighQualityPosters.has(image)) {
      highQualityUpgradeInFlight = false;
    }
    scheduleHighQualityPosterUpgrades();
    return;
  }
  if (image.dataset.posterQuality === 'low-loaded' || image.complete) {
    pendingHighQualityPosters.add(image);
    scheduleHighQualityPosterUpgrades();
  } else {
    pendingHighQualityPosters.add(image);
  }
}

/** Pause and reset upgrades on navigation; resume only after the page details settle. */
export function setHighQualityPostersReady(ready: boolean): void {
  if (!ready) {
    highQualityUpgradeGeneration += 1;
    cancelHighQualityUpgradeSchedule();
    highQualityUpgradeInFlight = false;
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
