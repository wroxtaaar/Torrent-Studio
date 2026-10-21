import { readPersistentSearchAvailability } from '../persistentCaches.ts';
import { useNexStreamState } from './useNexStreamState.ts';
import { useSearchMetadataState } from './useSearchMetadataState.ts';
import { useMoviePreviewState } from './useMoviePreviewState.ts';
import { useCatalogueNavigationState } from './useCatalogueNavigationState.ts';
import { useSearchInputState } from './useSearchInputState.ts';

export function useCancelSearch({ searchGenerationRef, searchRequestRef, setShowRecentSearches, setResults, movieTorrentSearchGenerationRef, movieTorrentSearchControllerRef, nexStreamSearchGenerationRef, nexStreamSearchControllerRef, setNexStreamLoading, setNexStreamSearchMode, setNexStreamResults, setNexStreamError, setIsSearching, setCatalogueBuildProgress, setError, setMovieCatalogue, setSearched, setSearchAvailabilityByGroup }: Pick<ReturnType<typeof useSearchInputState>, 'searchGenerationRef' | 'searchRequestRef' | 'setShowRecentSearches' | 'setResults'> & Pick<ReturnType<typeof useMoviePreviewState>, 'movieTorrentSearchGenerationRef' | 'movieTorrentSearchControllerRef'> & Pick<ReturnType<typeof useNexStreamState>, 'nexStreamSearchGenerationRef' | 'nexStreamSearchControllerRef' | 'setNexStreamLoading' | 'setNexStreamSearchMode' | 'setNexStreamResults' | 'setNexStreamError'> & Pick<ReturnType<typeof useCatalogueNavigationState>, 'setIsSearching' | 'setCatalogueBuildProgress' | 'setError' | 'setMovieCatalogue' | 'setSearched'> & Pick<ReturnType<typeof useSearchMetadataState>, 'setSearchAvailabilityByGroup'>) {
  const cancelSearch = () => {
    // Invalidate the active request before aborting so late responses cannot update the UI.
    searchGenerationRef.current += 1;
    searchRequestRef.current?.abort();
    searchRequestRef.current = null;
    movieTorrentSearchGenerationRef.current += 1;
    movieTorrentSearchControllerRef.current?.abort();
    movieTorrentSearchControllerRef.current = null;
    nexStreamSearchGenerationRef.current += 1;
    nexStreamSearchControllerRef.current?.abort();
    nexStreamSearchControllerRef.current = null;
    setNexStreamLoading(false);
    setNexStreamSearchMode(null);
    setNexStreamResults([]);
    setNexStreamError('');
    setIsSearching(false);
    setCatalogueBuildProgress('');
    setError('');
    setShowRecentSearches(false);
    setMovieCatalogue(null);
    setResults([]);
    setSearchAvailabilityByGroup(readPersistentSearchAvailability());
    setSearched(false);
  };

  return {
    cancelSearch,
  };
}
