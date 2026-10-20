import { useRef, useState } from 'react';
import { TorrentSearchResult } from '../../../api/client.ts';

export function useSearchInputState() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<TorrentSearchResult[]>([]);
  // Seed count is the default ranking so the strongest swarms appear first.
  // 720p/1080p are mutually exclusive. Size and Time are independent sort toggles.
  const [resolutionFilter, setResolutionFilter] = useState<'720p' | '1080p' | null>(null);
  const [sizeSort, setSizeSort] = useState<'asc' | 'desc' | null>(null);
  const [timeSort, setTimeSort] = useState<'desc' | 'asc' | null>(null);
  const [showRecentSearches, setShowRecentSearches] = useState(false);
  // Metadata is prefetched in small batches so search remains fast while the
  // most likely results are already resolved when the user clicks Add.
  const metadataCacheRef = useRef(new Map<string, {
    name: string;
    hash: string;
    files: { index: number; name: string; size: number; path: string; type: string; priority?: number }[];
    totalSize: number;
  }>());
  const recentSearchRef = useRef<HTMLDivElement | null>(null);
  const searchRequestRef = useRef<AbortController | null>(null);
  const searchGenerationRef = useRef(0);

  return {
    query,
    setQuery,
    results,
    setResults,
    resolutionFilter,
    setResolutionFilter,
    sizeSort,
    setSizeSort,
    timeSort,
    setTimeSort,
    showRecentSearches,
    setShowRecentSearches,
    metadataCacheRef,
    recentSearchRef,
    searchRequestRef,
    searchGenerationRef,
  };
}
