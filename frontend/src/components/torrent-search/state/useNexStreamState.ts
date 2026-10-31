import { useRef, useState } from 'react';
import { NexStreamTitle } from '../types.ts';

export function useNexStreamState() {
  const [nexStreamResults, setNexStreamResults] = useState<NexStreamTitle[]>([]);
  const [nexStreamSearchMode, setNexStreamSearchMode] = useState<'movie' | 'tv' | null>(null);
  const [nexStreamLoading, setNexStreamLoading] = useState(false);
  const [nexStreamLoadingTitle, setNexStreamLoadingTitle] = useState('');
  const [nexStreamEpisodePrefetchStatus, setNexStreamEpisodePrefetchStatus] = useState<Record<string, 'loading' | 'ready' | 'error'>>({});
  const nexStreamSearchControllerRef = useRef<AbortController | null>(null);
  const nexStreamSearchGenerationRef = useRef(0);
  const [nexStreamError, setNexStreamError] = useState('');
  const [nexStreamPlayer, setNexStreamPlayer] = useState<{ title: string; year?: string; sourceName: string; url: string; type: 'movie' | 'tv'; tmdbId?: number; season?: number; episode?: number; anime?: boolean } | null>(null);
  const [nexStreamResolvingId, setNexStreamResolvingId] = useState<string | null>(null);
  const [nexStreamEpisodePicker, setNexStreamEpisodePicker] = useState<NexStreamTitle | null>(null);
  const [nexStreamSeasons, setNexStreamSeasons] = useState<Array<{ seasonNumber: number; name: string; episodeCount: number }>>([]);
  const [nexStreamEpisodes, setNexStreamEpisodes] = useState<Array<{ episodeNumber: number; name: string; overview: string; airDate: string; still: string | null }>>([]);
  const [nexStreamSelectedSeason, setNexStreamSelectedSeason] = useState(1);
  const [nexStreamEpisodesLoading, setNexStreamEpisodesLoading] = useState(false);
  const [nexStreamEpisodesError, setNexStreamEpisodesError] = useState('');
  const [nexStreamEpisodesStatus, setNexStreamEpisodesStatus] = useState<'ready' | 'no_seasons' | 'no_episodes' | null>(null);

  return {
    nexStreamResults,
    setNexStreamResults,
    nexStreamSearchMode,
    setNexStreamSearchMode,
    nexStreamLoading,
    setNexStreamLoading,
    nexStreamLoadingTitle,
    setNexStreamLoadingTitle,
    nexStreamEpisodePrefetchStatus,
    setNexStreamEpisodePrefetchStatus,
    nexStreamSearchControllerRef,
    nexStreamSearchGenerationRef,
    nexStreamError,
    setNexStreamError,
    nexStreamPlayer,
    setNexStreamPlayer,
    nexStreamResolvingId,
    setNexStreamResolvingId,
    nexStreamEpisodePicker,
    setNexStreamEpisodePicker,
    nexStreamSeasons,
    setNexStreamSeasons,
    nexStreamEpisodes,
    setNexStreamEpisodes,
    nexStreamSelectedSeason,
    setNexStreamSelectedSeason,
    nexStreamEpisodesLoading,
    setNexStreamEpisodesLoading,
    nexStreamEpisodesError,
    setNexStreamEpisodesError,
    nexStreamEpisodesStatus,
    setNexStreamEpisodesStatus,
  };
}
