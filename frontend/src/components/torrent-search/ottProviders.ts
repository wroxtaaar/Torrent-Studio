import { MovieCatalogueItem, MovieOttAvailability, MovieOttProvider } from '../../api/client.ts';
import { type MovieCardProvider } from '../MovieCards.tsx';

export const PREFERRED_OTT_PROVIDERS = [
  'amazon prime video',
  'netflix',
  'sonyliv',
  'hotstar',
  'apple tv',
  'zee5',
];


export function normalizeOttProviderName(name: string): string {
  const normalized = String(name || '')
    .toLowerCase()
    .replace(/\\s*[-·:]\\s*(?:rent|buy|subscription|sub|streaming)\\s*$/i, '')
    .replace(/\\s+with\\s+ads?$/i, '')
    .replace(/\\s+(?:channel|add-on)$/i, '')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
    .replace(/\\s+/g, ' ');

  if (/^(?:primevideo|prime video|amazon video|amazon primevideo|amazon prime video)$/.test(normalized)) {
    return 'amazon prime video';
  }
  if (/^(?:appletv|apple tv|apple tv store|apple tv plus|apple tv channel)$/.test(normalized)) {
    return 'apple tv';
  }
  if (/^(?:jiohotstar|jio hotstar|hotstar)$/.test(normalized)) {
    return 'hotstar';
  }
  if (/^sonyliv$/.test(normalized)) return 'sonyliv';
  if (/^zee ?5$/.test(normalized)) return 'zee5';
  // TMDB can list the same service as both "MX Player" and "Amazon MX Player".
  if (/^(?:amazon )?mx player$/.test(normalized)) return 'mx player';
  if (normalized.startsWith('sony pictures ') && normalized.includes('amazon channel')) {
    return 'sony pictures amazon channel';
  }
  if (normalized.includes('lionsgate play')) return 'lionsgate play';
  return normalized;
}


export function displayOttProviderName(name: string): string {
  const key = normalizeOttProviderName(name);
  const preferredLabels: Record<string, string> = {
    'amazon prime video': 'Amazon Prime',
    'mx player': 'MX Player',
    netflix: 'Netflix',
    sonyliv: 'SonyLIV',
    hotstar: 'Hotstar',
    'apple tv': 'Apple TV',
    zee5: 'ZEE5',
  };
  if (preferredLabels[key]) return preferredLabels[key];
  return String(name || '')
    .replace(/\\s*[-·:]\\s*(?:rent|buy|subscription|sub|streaming)\\s*$/i, '')
    .replace(/\\s+with\\s+ads?$/i, '')
    .trim();
}


export function uniqueOttProviders<T extends { name: string; type?: string; webUrl?: string; providerId?: number | string | null }>(providers: T[]): T[] {
  const unique = new Map<string, T>();
  providers.forEach(provider => {
    const key = normalizeOttProviderName(provider.name);
    if (!key) return;
    const existing = unique.get(key);
    if (existing) {
      unique.set(key, {
        ...existing,
        webUrl: existing.webUrl || provider.webUrl,
        providerId: existing.providerId ?? provider.providerId,
      });
      return;
    }
    unique.set(key, { ...provider, name: displayOttProviderName(provider.name) });
  });

  const all = Array.from(unique.entries());
  const preferred = all.filter(([key]) => PREFERRED_OTT_PROVIDERS.includes(key));
  return (preferred.length ? preferred : all).map(([, provider]) => provider);
}


/** Maps provider objects to the shape the shared movie cards render. */
export function toCardProviders(
  providers: Array<{ name: string; webUrl?: string; providerId?: number | string | null }>,
): MovieCardProvider[] {
  return providers.map((provider, index) => {
    const name = displayOttProviderName(provider.name);
    return {
      key: String(provider.providerId ?? name ?? index).toLowerCase(),
      name,
      webUrl: provider.webUrl,
    };
  });
}


export const PLAYABLE_FILE_PATTERN = /\.(mkv|mp4|m4v|webm|mov|avi|m3u8|ts|mp3|wav|flac|aac|ogg|m4a)$/i;


export function normalizeSavedOttProviders(
  items: unknown,
  fallbackType = 'streaming',
  fallbackRegion = 'IN',
): Array<MovieOttProvider & { region: string; type: string }> {
  if (!Array.isArray(items)) return [];
  return items.flatMap((raw: any) => {
    const item = typeof raw === 'string'
      ? { name: raw }
      : raw && typeof raw === 'object'
        ? raw
        : null;
    const name = String(
      item?.name || item?.provider_name || item?.providerName || item?.provider || item?.title || ''
    ).trim();
    if (!name) return [];
    return [{
      name,
      region: String(item?.region || fallbackRegion || 'IN'),
      type: String(item?.type || fallbackType || 'streaming'),
      webUrl: item?.webUrl || item?.web_url || item?.url || undefined,
      logoUrl: item?.logoUrl || item?.logo_url || item?.logo_path || item?.logo || item?.image_url || undefined,
    }];
  });
}


export function savedOttAvailabilityForMovie(movie: MovieCatalogueItem): MovieOttAvailability | undefined {
  const saved = movie.ottAvailability;
  if (!saved || typeof saved !== 'object') return undefined;
  const region = String(saved.region || 'IN');
  const streamingProviders = normalizeSavedOttProviders(saved.streamingProviders, 'streaming', region);
  const rentProviders = normalizeSavedOttProviders(saved.rentProviders, 'rent', region);
  const buyProviders = normalizeSavedOttProviders(saved.buyProviders, 'buy', region);
  const savedStatus = String(saved.status || '').toLowerCase();
  return {
    movieId: Number(movie.tmdbId || movie.id),
    region,
    status: (
      savedStatus === 'streaming' ||
      savedStatus === 'streaming_info_found' ||
      streamingProviders.length > 0
    ) ? 'streaming'
      : (savedStatus === 'rent_buy' || rentProviders.length > 0 || buyProviders.length > 0) ? 'rent_buy'
      : savedStatus === 'digital_scheduled' ? 'digital_scheduled'
      : savedStatus === 'digital_release_known' ? 'digital_release_known'
      : 'not_confirmed',
    streamingProviders,
    rentProviders,
    buyProviders,
    providerLink: String(saved.providerLink || ''),
    checkedAt: String(saved.checkedAt || ''),
    source: String(saved.source || 'saved-catalogue'),
    providerAttribution: String(saved.providerAttribution || ''),
    attribution: String(saved.attribution || ''),
  };
}
