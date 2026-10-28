export function validMalId(value: unknown): value is number {
  const id = typeof value === 'number' ? value : Number(String(value ?? '').trim());
  return Number.isInteger(id) && id > 0;
}

export function validEpisode(value: unknown): value is number {
  const episode = typeof value === 'number' ? value : Number(String(value ?? '').trim());
  return Number.isInteger(episode) && episode > 0;
}

export function buildYenimeUrl(malId: unknown, episode: unknown, type: 'sub' | 'dub' = 'sub'): string {
  if (!validMalId(malId)) throw new Error('A positive MAL ID is required.');
  if (!validEpisode(episode)) throw new Error('A positive episode number is required.');
  if (type !== 'sub' && type !== 'dub') throw new Error('Stream type must be sub or dub.');
  return `https://megaplay.buzz/stream/mal/${Number(malId)}/${Number(episode)}/${type}`;
}

export const YENIME_ANIME_MAL_IDS: Record<string, number> = {
  'Fullmetal Alchemist: Brotherhood': 5114,
};

export function yenimeMalIdForTitle(title: string): number | undefined {
  return YENIME_ANIME_MAL_IDS[title];
}

export function isAnimeCatalogue(catalogue: string | null | undefined): boolean {
  return catalogue === 'classics-anime';
}
