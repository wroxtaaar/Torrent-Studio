import { useRef, useState } from 'react';
import { TvCataloguePage } from '../../../api/client.ts';

export function useWebSeriesState() {
  const [regionalWebSeriesCatalogue, setRegionalWebSeriesCatalogue] = useState<TvCataloguePage | null>(null);
  const [regionalWebSeriesLoading, setRegionalWebSeriesLoading] = useState(false);
  const [regionalWebSeriesError, setRegionalWebSeriesError] = useState('');
  const [showDcWebSeries, setShowDcWebSeries] = useState(false);
  const [dcWebSeriesCatalogue, setDcWebSeriesCatalogue] = useState<TvCataloguePage | null>(null);
  const [dcWebSeriesLoading, setDcWebSeriesLoading] = useState(false);
  const [dcWebSeriesError, setDcWebSeriesError] = useState('');
  const dcWebSeriesRequestGenerationRef = useRef(0);
  const [marvelWebSeriesCatalogue, setMarvelWebSeriesCatalogue] = useState<TvCataloguePage | null>(null);
  const [marvelWebSeriesLoading, setMarvelWebSeriesLoading] = useState(false);
  const [marvelWebSeriesError, setMarvelWebSeriesError] = useState('');

  return {
    regionalWebSeriesCatalogue,
    setRegionalWebSeriesCatalogue,
    regionalWebSeriesLoading,
    setRegionalWebSeriesLoading,
    regionalWebSeriesError,
    setRegionalWebSeriesError,
    showDcWebSeries,
    setShowDcWebSeries,
    dcWebSeriesCatalogue,
    setDcWebSeriesCatalogue,
    dcWebSeriesLoading,
    setDcWebSeriesLoading,
    dcWebSeriesError,
    setDcWebSeriesError,
    dcWebSeriesRequestGenerationRef,
    marvelWebSeriesCatalogue,
    setMarvelWebSeriesCatalogue,
    marvelWebSeriesLoading,
    setMarvelWebSeriesLoading,
    marvelWebSeriesError,
    setMarvelWebSeriesError,
  };
}
