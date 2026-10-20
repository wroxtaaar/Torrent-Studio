import { useRef, useState } from 'react';
import { TorrentSearchResult } from '../../../api/client.ts';

export function usePosterState() {
  // Poster resolution runs independently of torrent search and ranking.
  // Results are queued in seed order, but only two background resolutions run
  // at once so this never becomes a search bottleneck.
  const [posterOverrides, setPosterOverrides] = useState<Record<string, string>>({});
  const [metadataPosterFailed, setMetadataPosterFailed] = useState<Record<string, boolean>>({});
  const posterTitleCacheLoadedRef = useRef(false);
  const posterLoadedRef = useRef(new Set<string>());
  const posterMetadataFailedRef = useRef(new Set<string>());
  const posterBackgroundQueueRef = useRef<Array<{ key: string; result: TorrentSearchResult }>>([]);
  const posterBackgroundQueuedRef = useRef(new Set<string>());
  const posterBackgroundActiveRef = useRef(0);
  // Track the keys currently being resolved; queued-only checks miss active jobs.
  const posterBackgroundActiveKeysRef = useRef(new Set<string>());
  const posterBackgroundGenerationRef = useRef(0);
  const posterBackgroundAttemptsRef = useRef(new Map<string, number>());
  // Avoid repeating an identical failed poster request for every quality/variant
  // of the same title. 404s expire after ten minutes so later retries can recover.
  const posterResolveCacheRef = useRef(new Map<string, { url: string; expiresAt: number }>());

  return {
    posterOverrides,
    setPosterOverrides,
    metadataPosterFailed,
    setMetadataPosterFailed,
    posterTitleCacheLoadedRef,
    posterLoadedRef,
    posterMetadataFailedRef,
    posterBackgroundQueueRef,
    posterBackgroundQueuedRef,
    posterBackgroundActiveRef,
    posterBackgroundActiveKeysRef,
    posterBackgroundGenerationRef,
    posterBackgroundAttemptsRef,
    posterResolveCacheRef,
  };
}
