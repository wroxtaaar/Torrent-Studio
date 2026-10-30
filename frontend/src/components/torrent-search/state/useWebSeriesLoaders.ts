import { api } from '../../../api/client.ts';
import { tvCataloguePageFromSection, tvCatalogueSection } from '../../../api/sectionCache.ts';
import { useCatalogueNavigationState } from './useCatalogueNavigationState.ts';
import { useWebSeriesState } from './useWebSeriesState.ts';

async function loadTvCataloguePage(catalogue: string, page = 1) {
  const section = tvCatalogueSection(catalogue);
  if (!section) return api.getTvCatalogue(catalogue, page);
  const document = await api.getSectionCache(section.section);
  const result = tvCataloguePageFromSection(document, catalogue, section.subsection, page);
  if (!result) throw new Error('The requested TV subsection is missing from its section cache.');
  return result;
}

export function useWebSeriesLoaders({ searchGenerationRef, setShowDcWebSeries, dcWebSeriesCatalogue, dcWebSeriesLoading, setDcWebSeriesLoading, setDcWebSeriesError, setDcWebSeriesCatalogue, marvelWebSeriesCatalogue, setMarvelWebSeriesCatalogue, setMarvelWebSeriesLoading, setMarvelWebSeriesError, marvelWebSeriesLoading, setShowMarvelWebSeries, error, setClassicsContentTab }: { searchGenerationRef: { current: number } } & Pick<ReturnType<typeof useWebSeriesState>, 'setShowDcWebSeries' | 'dcWebSeriesCatalogue' | 'dcWebSeriesLoading' | 'setDcWebSeriesLoading' | 'setDcWebSeriesError' | 'setDcWebSeriesCatalogue' | 'marvelWebSeriesCatalogue' | 'setMarvelWebSeriesCatalogue' | 'setMarvelWebSeriesLoading' | 'setMarvelWebSeriesError' | 'marvelWebSeriesLoading'> & Pick<ReturnType<typeof useCatalogueNavigationState>, 'setShowMarvelWebSeries' | 'error' | 'setClassicsContentTab'>) {
  const loadDcWebSeries = async () => {
    setShowDcWebSeries(true);
    setShowMarvelWebSeries(false);
    if (dcWebSeriesCatalogue || dcWebSeriesLoading) return;
    setDcWebSeriesLoading(true);
    setDcWebSeriesError('');
    // Any newer section action bumps the counter, so a late answer cannot reappear after switching away.
    const generation = ++searchGenerationRef.current;
    try {
      const page = await loadTvCataloguePage('dc-live-action');
      if (generation === searchGenerationRef.current) setDcWebSeriesCatalogue(page);
    } catch (error: any) {
      if (generation === searchGenerationRef.current) setDcWebSeriesError(String(error?.message || 'Could not load DC web series.'));
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
    const generation = ++searchGenerationRef.current;
    try {
      const page = await loadTvCataloguePage(catalogueKey);
      if (generation === searchGenerationRef.current) setMarvelWebSeriesCatalogue(page);
    } catch (error: any) {
      if (generation === searchGenerationRef.current) setMarvelWebSeriesError(String(error?.message || 'Could not load Classics catalogue.'));
    } finally {
      setMarvelWebSeriesLoading(false);
    }
  };
  const loadMarvelWebSeries = async () => {
    setShowMarvelWebSeries(true);
    if (marvelWebSeriesCatalogue?.catalogue === 'marvel-web-series' || marvelWebSeriesLoading) return;
    setMarvelWebSeriesLoading(true);
    setMarvelWebSeriesError('');
    const generation = ++searchGenerationRef.current;
    try {
      // Fetch every page up front so the Marvel section is complete rather than
      // silently showing only the first page until the user finds Load more.
      const firstPage = await loadTvCataloguePage('marvel', 1);
      const allResults = [...firstPage.results];
      for (let page = 2; page <= Math.min(firstPage.totalPages, 500); page += 1) {
        if (generation !== searchGenerationRef.current) return;
        const nextPage = await loadTvCataloguePage('marvel', page);
        for (const show of nextPage.results) {
          if (!allResults.some(existing => String(existing.id) === String(show.id))) allResults.push(show);
        }
      }
      if (generation === searchGenerationRef.current) setMarvelWebSeriesCatalogue({ ...firstPage, page: firstPage.totalPages, results: allResults });
    } catch (error: any) {
      if (generation === searchGenerationRef.current) setMarvelWebSeriesError(String(error?.message || 'Could not load Marvel web series.'));
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
