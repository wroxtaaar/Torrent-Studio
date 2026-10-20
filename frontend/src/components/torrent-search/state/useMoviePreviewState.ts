import { useRef, useState } from 'react';
import { MovieCatalogueItem } from '../../../api/client.ts';
import { TorrentQualityGroup } from '../grouping.ts';

export function useMoviePreviewState() {
  // Search results are compact cards until the user opens one with Get.
  // The live search, posters, OTT lookups and metadata prefetch keep running independently.
  const [expandedSearchGroupKey, setExpandedSearchGroupKey] = useState<string | null>(null);
  const [movieTorrentPreviewGroup, setMovieTorrentPreviewGroup] = useState<TorrentQualityGroup | null>(null);
  // A TMDB ID alone is not unique across catalogue views. Scope a Prepare
  // preview to the exact catalogue item the user clicked.
  const [movieTorrentPreviewCatalogueId, setMovieTorrentPreviewCatalogueId] = useState<string | null>(null);
  const [pendingPosterAction, setPendingPosterAction] = useState<
    | { kind: 'catalogue'; movie: MovieCatalogueItem; catalogue: string; page: number }
    | { kind: 'search'; groupKey: string; page: number }
    | null
  >(null);
  // Preserve the exact poster URL from the catalogue card the user clicked.
  // The selected inline card must keep using that same source, even while the
  // catalogue list re-renders or torrent metadata is substituted.
  const [movieTorrentPreviewPosterUrl, setMovieTorrentPreviewPosterUrl] = useState('');
  // Capture the URL of the poster that actually loaded in the original catalogue card.
  const cataloguePosterUrlsRef = useRef<Record<string, string>>({});
  const searchPosterUrlsRef = useRef<Record<string, string>>({});
  const [movieTorrentPickerGroups, setMovieTorrentPickerGroups] = useState<TorrentQualityGroup[] | null>(null);
  const [movieTorrentSearchLoading, setMovieTorrentSearchLoading] = useState(false);
  const [movieTorrentSearchTitle, setMovieTorrentSearchTitle] = useState('');
  const [movieTorrentSearchError, setMovieTorrentSearchError] = useState('');
  const [selectedMovieTorrentQualityByGroup, setSelectedMovieTorrentQualityByGroup] = useState<Record<string, string>>({});
  const movieTorrentSearchControllerRef = useRef<AbortController | null>(null);
  const movieTorrentSearchGenerationRef = useRef(0);
  const prepareClickIntentRef = useRef(false);
  const prepareTraceIdRef = useRef<string | null>(null);
  // Keep per-title torrent results and grouped quality variants in memory across
  // catalogue switches, so reopening a Bollywood/Hollywood movie uses the same
  // already-resolved details as Marvel instead of repeating provider searches.
  const movieTorrentDetailsCacheRef = useRef(new Map<string, {
    groups: TorrentQualityGroup[];
    savedAt: number;
  }>());

  return {
    expandedSearchGroupKey,
    setExpandedSearchGroupKey,
    movieTorrentPreviewGroup,
    setMovieTorrentPreviewGroup,
    movieTorrentPreviewCatalogueId,
    setMovieTorrentPreviewCatalogueId,
    pendingPosterAction,
    setPendingPosterAction,
    movieTorrentPreviewPosterUrl,
    setMovieTorrentPreviewPosterUrl,
    cataloguePosterUrlsRef,
    searchPosterUrlsRef,
    movieTorrentPickerGroups,
    setMovieTorrentPickerGroups,
    movieTorrentSearchLoading,
    setMovieTorrentSearchLoading,
    movieTorrentSearchTitle,
    setMovieTorrentSearchTitle,
    movieTorrentSearchError,
    setMovieTorrentSearchError,
    selectedMovieTorrentQualityByGroup,
    setSelectedMovieTorrentQualityByGroup,
    movieTorrentSearchControllerRef,
    movieTorrentSearchGenerationRef,
    prepareClickIntentRef,
    prepareTraceIdRef,
    movieTorrentDetailsCacheRef,
  };
}
