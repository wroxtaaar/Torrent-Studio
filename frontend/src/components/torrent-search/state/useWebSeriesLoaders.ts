import { api } from '../../../api/client.ts';
import { useCatalogueNavigationState } from './useCatalogueNavigationState.ts';
import { useWebSeriesState } from './useWebSeriesState.ts';

export function useWebSeriesLoaders({ setShowDcWebSeries, dcWebSeriesCatalogue, dcWebSeriesLoading, setDcWebSeriesLoading, setDcWebSeriesError, setDcWebSeriesCatalogue, marvelWebSeriesCatalogue, setMarvelWebSeriesCatalogue, setMarvelWebSeriesLoading, setMarvelWebSeriesError, marvelWebSeriesLoading, setShowMarvelWebSeries, error, setClassicsContentTab }: Pick<ReturnType<typeof useWebSeriesState>, 'setShowDcWebSeries' | 'dcWebSeriesCatalogue' | 'dcWebSeriesLoading' | 'setDcWebSeriesLoading' | 'setDcWebSeriesError' | 'setDcWebSeriesCatalogue' | 'marvelWebSeriesCatalogue' | 'setMarvelWebSeriesCatalogue' | 'setMarvelWebSeriesLoading' | 'setMarvelWebSeriesError' | 'marvelWebSeriesLoading'> & Pick<ReturnType<typeof useCatalogueNavigationState>, 'setShowMarvelWebSeries' | 'error' | 'setClassicsContentTab'>) {
  const loadDcWebSeries = async () => {
    setShowDcWebSeries(true);
    setShowMarvelWebSeries(false);
    if (dcWebSeriesCatalogue || dcWebSeriesLoading) return;
    setDcWebSeriesLoading(true);
    setDcWebSeriesError('');
    try {
      setDcWebSeriesCatalogue(await api.getTvCatalogue('dc-live-action'));
    } catch (error: any) {
      setDcWebSeriesError(String(error?.message || 'Could not load DC web series.'));
    } finally {
      setDcWebSeriesLoading(false);
    }
  };
  const loadClassicsTvCatalogue = async (catalogueKey: 'classics-web-series' | 'classics-anime', tab: 'web-series' | 'anime') => {
    setClassicsContentTab(tab);
    setShowDcWebSeries(false);
    setShowMarvelWebSeries(true);
    if (marvelWebSeriesCatalogue?.catalogue === catalogueKey) return;
    setMarvelWebSeriesCatalogue(null);
    setMarvelWebSeriesLoading(true);
    setMarvelWebSeriesError('');
    try {
      setMarvelWebSeriesCatalogue(await api.getTvCatalogue(catalogueKey));
    } catch (error: any) {
      setMarvelWebSeriesError(String(error?.message || 'Could not load Classics catalogue.'));
    } finally {
      setMarvelWebSeriesLoading(false);
    }
  };
  const loadMarvelWebSeries = async () => {
    setShowMarvelWebSeries(true);
    if (marvelWebSeriesCatalogue?.catalogue === 'marvel-web-series' || marvelWebSeriesLoading) return;
    setMarvelWebSeriesLoading(true);
    setMarvelWebSeriesError('');
    try {
      // Fetch every page up front so the Marvel section is complete rather than
      // silently showing only the first page until the user finds Load more.
      const firstPage = await api.getTvCatalogue('marvel', 1);
      const allResults = [...firstPage.results];
      for (let page = 2; page <= Math.min(firstPage.totalPages, 500); page += 1) {
        const nextPage = await api.getTvCatalogue('marvel', page);
        for (const show of nextPage.results) {
          if (!allResults.some(existing => String(existing.id) === String(show.id))) allResults.push(show);
        }
      }
      setMarvelWebSeriesCatalogue({ ...firstPage, page: firstPage.totalPages, results: allResults });
    } catch (error: any) {
      setMarvelWebSeriesError(String(error?.message || 'Could not load Marvel web series.'));
    } finally {
      setMarvelWebSeriesLoading(false);
    }
  };

  return {
    loadDcWebSeries,
    loadClassicsTvCatalogue,
    loadMarvelWebSeries,
  };
}
