import { Loader2 } from 'lucide-react';
import type { RegionalTvGroup, RegionalTvMode } from '../types.ts';
import { imdbRatingKey } from '../grouping.ts';
import { TvShowTile } from '../TvShowTile.tsx';
import type { PanelModel } from '../useTorrentSearchPanel.tsx';
import { CatalogueBar, CATALOGUE_SORTS } from '../CatalogueBar.tsx';

const REGIONAL_SECTIONS = ['hollywood', 'bollywood', 'korean', 'pakistani', 'anime'] as const;

export function RegionalTvCatalogueSection({ vm }: { vm: PanelModel }) {
  const {
    activeTopSection,
    catalogueSort,
    imdbRatingsByKey,
    openRegionalTvCatalogue,
    playCatalogueTvWithNexStream,
    openYenimeRequest,
    regionalContentTabs,
    regionalWebSeriesCatalogue,
    regionalWebSeriesError,
    regionalWebSeriesLoading,
  } = vm;

  const activeRegionalSection = REGIONAL_SECTIONS.find(section => section === activeTopSection);
  const isHighestRatedTv = activeTopSection === 'highest-rated';
  if (!isHighestRatedTv && (!activeRegionalSection || regionalContentTabs[activeRegionalSection] !== 'web-series')) {
    return null;
  }

  const catalogue = regionalWebSeriesCatalogue;
  if (isHighestRatedTv && !catalogue?.catalogue.startsWith('highest-rated-')) return null;
  const catalogueKey = catalogue?.catalogue || '';
  const group = (catalogueKey.startsWith('highest-rated-') ? 'highest-rated' : catalogueKey.split('-')[0]) as RegionalTvGroup | undefined;
  const mode = (catalogueKey.startsWith('highest-rated-') ? catalogueKey.slice('highest-rated-'.length) : catalogueKey.split('-').slice(1).join('-')) as RegionalTvMode | undefined;
  const page = catalogue?.page || 1;
  const totalPages = Math.max(1, catalogue?.totalPages || 1);
  const canNavigate = Boolean(group && mode);
  const showSortButtons = true;
  const sortedShows = (() => {
    const rows = catalogue?.results ?? [];
    // Some curated anime feeds can contain the same series more than once
    // under different source IDs. Keep the first occurrence to preserve the
    // source's popularity order, and don't render duplicate cards.
    const seen = new Set<string>();
    const uniqueRows = rows.filter(show => {
      const titleKey = String(show.title || '').toLowerCase().replace(/[^a-z0-9]+/g, '');
      const yearKey = Number(show.year) || 0;
      const key = `${titleKey}:${yearKey}`;
      if (!titleKey || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
    if (!showSortButtons || catalogueSort === 'popularity') return uniqueRows;
    return uniqueRows
      .map((show, index) => ({ show, index }))
      .sort((a, b) => {
        if (catalogueSort === 'rating') {
          const ratingOf = (show: typeof a.show) =>
            Number(show.imdbRating) ||
            Number(imdbRatingsByKey[imdbRatingKey(show.title, show.year, 'tv')]?.imdbRating) ||
            0;
          return ratingOf(b.show) - ratingOf(a.show) || a.index - b.index;
        }
        const yearOf = (show: typeof a.show) =>
          Number(show.year) || Number(String(show.releaseDate || '').match(/^(\d{4})/)?.[1]) || 0;
        return yearOf(b.show) - yearOf(a.show) || a.index - b.index;
      })
      .map(({ show }) => show);
  })();
  const navigate = (nextPage: number) => {
    if (group && mode) void openRegionalTvCatalogue(group, mode, nextPage, false);
  };
  const bar = (withSort: boolean) => (
    <CatalogueBar page={page} totalPages={totalPages} busy={regionalWebSeriesLoading || !canNavigate}
      onPrev={() => navigate(page - 1)} onNext={() => navigate(page + 1)}
      sort={withSort && sortedShows.length > 0 ? { options: CATALOGUE_SORTS.map(option => ({ ...option, active: catalogueSort === option.key })), onPick: key => vm.setCatalogueSort(key as typeof catalogueSort) } : undefined} />
  );
  const title = ({
    'highest-rated': 'Highest Rated TV Shows',
    hollywood: 'Hollywood Web Series',
    bollywood: 'Indian Web Series',
    korean: 'Korean Dramas',
    pakistani: 'Pakistani Dramas',
    anime: 'Anime Series',
  } as Record<string, string>)[isHighestRatedTv ? 'highest-rated' : activeRegionalSection || 'hollywood'];

  return (
    <section className="space-y-3">
      {regionalWebSeriesLoading && (
        <div className="flex items-center gap-3 rounded-xl border border-cyan-500/30 bg-slate-950 px-3 py-3 text-sm text-slate-200">
          <Loader2 className="h-5 w-5 shrink-0 animate-spin text-cyan-400" />
          <span>Loading {title.toLowerCase()}…</span>
        </div>
      )}
      {regionalWebSeriesError && (
        <div role="alert" className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-3 text-xs text-amber-200">
          {regionalWebSeriesError}
        </div>
      )}

      {catalogue && bar(true)}



      {catalogue && sortedShows.length > 0 && !regionalWebSeriesLoading && (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 lg:gap-4">
            {sortedShows.map(show => (
              <TvShowTile
                key={String(show.id)}
                show={show}
                imdb={imdbRatingsByKey[imdbRatingKey(show.title, show.year, 'tv')]}
                torrents={isHighestRatedTv || activeRegionalSection !== 'hollywood'}
                onPlay={() => {
                  if (activeRegionalSection === 'anime') openYenimeRequest(show.title, show.year, show.malId, 1, show.id);
                  else playCatalogueTvWithNexStream(show);
                }}
              />
            ))}
          </div>

        </>
      )}



      {catalogue && bar(false)}



      {catalogue && catalogue.results.length === 0 && !regionalWebSeriesLoading && (
        <div className="rounded-xl border border-slate-800 bg-slate-900 px-4 py-5 text-sm text-slate-400">
          No playable series were resolved for this page. Try another page.
        </div>
      )}
    </section>
  );
}
