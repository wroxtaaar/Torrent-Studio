import { useRef, useState } from 'react';
import { ImdbRatingResult, SearchMediaMetadata } from '../../../api/client.ts';
import { readPersistentImdbRatings, readPersistentSearchAvailability, readPersistentSearchMetadata } from '../persistentCaches.ts';

export function useSearchMetadataState() {
  const [searchMetadata, setSearchMetadata] = useState<SearchMediaMetadata[]>(readPersistentSearchMetadata);
  const [searchMetadataStatus, setSearchMetadataStatus] = useState<'idle' | 'loading' | 'ready' | 'not_found' | 'unavailable'>('idle');
  const [imdbRatingsByKey, setImdbRatingsByKey] = useState<Record<string, ImdbRatingResult>>(readPersistentImdbRatings);
  const imdbRatingRequestedRef = useRef(new Set<string>());
  const [imdbRetryTick, setImdbRetryTick] = useState(0);
  const imdbInFlightRef = useRef(0);
  const imdbRetryCountRef = useRef(0);
  const tvMetadataRequestedRef = useRef(new Set<string>());
  const [searchAvailabilityByGroup, setSearchAvailabilityByGroup] = useState(readPersistentSearchAvailability);
  const [selectedQualityByGroup, setSelectedQualityByGroup] = useState<Record<string, string>>({});

  return {
    searchMetadata,
    setSearchMetadata,
    searchMetadataStatus,
    setSearchMetadataStatus,
    imdbRatingsByKey,
    setImdbRatingsByKey,
    imdbRatingRequestedRef,
    imdbRetryTick,
    setImdbRetryTick,
    imdbInFlightRef,
    imdbRetryCountRef,
    tvMetadataRequestedRef,
    searchAvailabilityByGroup,
    setSearchAvailabilityByGroup,
    selectedQualityByGroup,
    setSelectedQualityByGroup,
  };
}
