import { useRef, useState } from 'react';
import { api } from '../../../api/client.ts';
import { fetchNexStreamEpisodeMetadata, type NexStreamEpisode, type NexStreamSeason } from '../nexstream.ts';
import { buildYenimeUrl, yenimeMalIdForTitle } from '../yenime.ts';

export type YenimePlayerRequest = {
  title: string;
  malId: number;
  episode: number;
  season: number;
  tmdbId?: number;
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
  const [yenimeEpisodePicker, setYenimeEpisodePicker] = useState<{ title: string; tmdbId?: number } | null>(null);
  const [yenimeSeasons, setYenimeSeasons] = useState<NexStreamSeason[]>([]);
  const [yenimeEpisodes, setYenimeEpisodes] = useState<NexStreamEpisode[]>([]);
  const [yenimeSelectedSeason, setYenimeSelectedSeason] = useState(1);
  const [yenimeEpisodesLoading, setYenimeEpisodesLoading] = useState(false);
  const [yenimeEpisodesError, setYenimeEpisodesError] = useState('');
  const [yenimeProvider, setYenimeProvider] = useState<'yenime' | 'vidrift'>('yenime');
  const generationRef = useRef(0);
  const episodeLoadGenerationRef = useRef(0);

  const loadYenimeEpisodes = async (tmdbId: number, season: number) => {
    const generation = ++episodeLoadGenerationRef.current;
    setYenimeEpisodesLoading(true);
    setYenimeEpisodesError('');
    try {
      const data = await fetchNexStreamEpisodeMetadata(tmdbId, season);
      if (generation !== episodeLoadGenerationRef.current) return;
      setYenimeSeasons(data.seasons);
      setYenimeEpisodes(data.episodes);
      setYenimeSelectedSeason(data.selectedSeason);
    } catch (error: unknown) {
      if (generation !== episodeLoadGenerationRef.current) return;
      setYenimeEpisodes([]);
      setYenimeEpisodesError(error instanceof Error ? error.message : 'Could not load episode list.');
    } finally {
      if (generation === episodeLoadGenerationRef.current) setYenimeEpisodesLoading(false);
    }
  };

  const closeYenimeEpisodePicker = () => {
    generationRef.current += 1;
    episodeLoadGenerationRef.current += 1;
    setYenimeEpisodePicker(null);
    setYenimeEpisodes([]);
    setYenimeSeasons([]);
    setYenimeEpisodesError('');
    setYenimeRequest(null);
  };

  const openYenimeRequest = (title: string, year?: number | null, catalogueMalId?: number | string | null, episode?: number | string | null, tmdbId?: number | string | null, season?: number | string | null) => {
    const generation = ++generationRef.current;
    setYenimePlayer(null);
    setYenimeProvider('yenime');
    const numericTmdbId = Number(tmdbId);
    const validTmdbId = Number.isInteger(numericTmdbId) && numericTmdbId > 0 ? numericTmdbId : undefined;
    const numericSeason = Number(season);
    const validSeason = Number.isInteger(numericSeason) && numericSeason > 0 ? numericSeason : 1;
    const existingMalId = catalogueMalId || yenimeMalIdForTitle(title);
    setYenimeSelectedSeason(validSeason);
    setYenimeEpisodePicker({ title, tmdbId: validTmdbId });
    setYenimeEpisodes([]);
    setYenimeSeasons([]);
    setYenimeEpisodesError(validTmdbId ? '' : 'Episode artwork and dates are unavailable, but you can still enter an episode number below.');
    setYenimeRequest({
      title,
      malId: existingMalId?.toString() || '',
      episode: String(Number(episode) > 0 ? Number(episode) : 1),
      type: 'sub',
      error: '',
      resolving: !existingMalId,
    });
    if (validTmdbId) void loadYenimeEpisodes(validTmdbId, validSeason);

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
    episodeLoadGenerationRef.current += 1;
    setYenimeRequest(null);
    setYenimePlayer(null);
    setYenimeEpisodePicker(null);
    setYenimeEpisodes([]);
    setYenimeSeasons([]);
    setYenimeEpisodesError('');
  };

  const launchYenime = (malIdText: string, episodeText: string, type: 'sub' | 'dub') => {
    if (!yenimeRequest) return;
    try {
      const malId = Number(malIdText);
      const episode = Number(episodeText);
      const url = buildYenimeUrl(malId, episode, type);
      const tmdbId = yenimeEpisodePicker?.tmdbId;
      setYenimeRequest(null);
      setYenimeEpisodePicker(null);
      setYenimeEpisodes([]);
      setYenimeProvider('yenime');
      setYenimePlayer({ title: yenimeRequest.title, malId, episode, season: yenimeSelectedSeason, tmdbId, type, url });
    } catch (error: unknown) {
      setYenimeRequest(current => current ? { ...current, error: error instanceof Error ? error.message : 'Could not open Yenime.' } : current);
    }
  };

  return {
    yenimeRequest, yenimePlayer, yenimeEpisodePicker, yenimeSeasons, yenimeEpisodes,
    yenimeSelectedSeason, yenimeEpisodesLoading, yenimeEpisodesError, yenimeProvider,
    setYenimePlayer, setYenimeRequest, setYenimeSelectedSeason, setYenimeProvider,
    openYenimeRequest, closeYenime, closeYenimeEpisodePicker,
    loadYenimeEpisodes, launchYenime,
  };
}
