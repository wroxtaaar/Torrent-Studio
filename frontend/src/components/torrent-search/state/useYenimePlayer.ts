import { useRef, useState } from 'react';
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
  } | null>(null);
  const [yenimePlayer, setYenimePlayer] = useState<YenimePlayerRequest | null>(null);
  const generationRef = useRef(0);

  const openYenimeRequest = (title: string) => {
    generationRef.current += 1;
    setYenimePlayer(null);
    setYenimeRequest({
      title,
      malId: yenimeMalIdForTitle(title)?.toString() || '',
      episode: '1',
      type: 'sub',
      error: '',
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
