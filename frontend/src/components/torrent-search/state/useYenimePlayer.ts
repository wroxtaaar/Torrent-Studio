import { useRef, useState } from 'react';
import { api } from '../../../api/client.ts';
import { buildYenimeUrl, yenimeMalIdForTitle } from '../yenime.ts';

export type YenimePlayerRequest = {
  title: string;
  malId: number;
  episode: number;
  type: 'sub' | 'dub';
  url: string;
};

export function useYenimePlayer() {
  const [yenimeRequest, setYenimeRequest] = useState<{
    title: string;
    malId: string;
    episode: string;
    type: 'sub' | 'dub';
    error: string;
    resolving: boolean;
  } | null>(null);
  const [yenimePlayer, setYenimePlayer] = useState<YenimePlayerRequest | null>(null);
  const generationRef = useRef(0);

  const openYenimeRequest = (title: string, year?: number | null, catalogueMalId?: number | string | null, episode?: number | string | null) => {
    const generation = ++generationRef.current;
    setYenimePlayer(null);
    const existingMalId = catalogueMalId || yenimeMalIdForTitle(title);
    setYenimeRequest({
      title,
      malId: existingMalId?.toString() || '',
      episode: String(Number(episode) > 0 ? Number(episode) : 1),
      type: 'sub',
      error: '',
      resolving: !existingMalId,
    });

    if (existingMalId) return;
    void api.resolveYenimeMalId(title, year, null).then(result => {
      if (generation !== generationRef.current) return;
      setYenimeRequest(current => {
        if (!current) return current;
        if (result.status === 'resolved' && result.malId) {
          return { ...current, malId: String(result.malId), resolving: false, error: '' };
        }
        const message = result.message || (result.status === 'ambiguous'
          ? 'Multiple matches were found. Enter the correct MAL ID manually.'
          : 'No confident MAL ID match was found. Enter the MAL ID manually.');
        return { ...current, resolving: false, error: message };
      });
    }).catch((error: unknown) => {
      if (generation !== generationRef.current) return;
      setYenimeRequest(current => current ? { ...current, resolving: false, error: error instanceof Error ? error.message : 'Could not resolve the MAL ID automatically.' } : current);
    });
  };

  const closeYenime = () => {
    generationRef.current += 1;
    setYenimeRequest(null);
    setYenimePlayer(null);
  };

  const launchYenime = (malIdText: string, episodeText: string, type: 'sub' | 'dub') => {
    if (!yenimeRequest) return;
    try {
      const malId = Number(malIdText);
      const episode = Number(episodeText);
      const url = buildYenimeUrl(malId, episode, type);
      setYenimeRequest(null);
      setYenimePlayer({ title: yenimeRequest.title, malId, episode, type, url });
    } catch (error: unknown) {
      setYenimeRequest(current => current ? { ...current, error: error instanceof Error ? error.message : 'Could not open Yenime.' } : current);
    }
  };

  return { yenimeRequest, yenimePlayer, setYenimeRequest, setYenimePlayer, openYenimeRequest, closeYenime, launchYenime };
}
