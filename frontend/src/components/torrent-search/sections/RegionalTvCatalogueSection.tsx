import { Loader2 } from 'lucide-react';
import type { RegionalTvGroup, RegionalTvMode } from '../types.ts';
import { imdbRatingKey } from '../grouping.ts';
import { TvShowCard } from '../TvShowCard.tsx';
import type { PanelModel } from '../useTorrentSearchPanel.tsx';

const REGIONAL_SECTIONS = ['hollywood', 'bollywood', 'korean', 'pakistani', 'anime'] as const;

export function RegionalTvCatalogueSection({ vm }: { vm: PanelModel }) {
  const {
    activeTopSection,
    imdbRatingsByKey,
    openRegionalTvCatalogue,
    playCatalogueTvWithNexStream,
    regionalContentTabs,
    regionalWebSeriesCatalogue,
    regionalWebSeriesError,
    regionalWebSeriesLoading,
  } = vm;

  const activeRegionalSection = REGIONAL_SECTIONS.find(section => section === activeTopSection);
  if (!activeRegionalSection || regionalContentTabs[activeRegionalSection] !== 'web-series') {
    return null;
  }

  const catalogue = regionalWebSeriesCatalogue;
  const [groupText, ...modeParts] = catalogue?.catalogue.split('-') || [];
  const group = groupText as RegionalTvGroup | undefined;
  const mode = modeParts.join('-') as RegionalTvMode | undefined;
  const page = catalogue?.page || 1;
  const totalPages = Math.max(1, catalogue?.totalPages || 1);
  const canNavigate = Boolean(group && mode);
  const navigate = (nextPage: number) => {
    if (group && mode) void openRegionalTvCatalogue(group, mode, nextPage);
  };
  const title = ({
    hollywood: 'Hollywood Web Series',
    bollywood: 'Indian Web Series',
    korean: 'Korean Dramas',
    pakistani: 'Pakistani Dramas',
    anime: 'Anime Series',
  } as Record<string, string>)[activeRegionalSection];

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2 px-1">
        <div className="text-xs text-slate-400">
          {title}
          {catalogue && <> · {catalogue.totalResults.toLocaleString()} series · Page {page} of {totalPages.toLocaleString()}</>}
          {catalogue && <> · Metadata by {catalogue.provider}</>}
        </div>
      </div>

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

      {catalogue && catalogue.results.length > 0 && (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 lg:gap-4">
            {catalogue.results.map(show => (
              <TvShowCard
                key={String(show.id)}
                show={show}
                imdb={imdbRatingsByKey[imdbRatingKey(show.title, show.year, 'tv')]}
                preferImdb
                onOpen={() => {
                  if (activeRegionalSection === 'anime') openYenimeRequest(show.title, show.year, show.malId, 1, show.id);
                  else if (activeRegionalSection !== 'korean') playCatalogueTvWithNexStream(show);
                }}
              />
            ))}
          </div>

          <div className="flex items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-900 px-3 py-2">
            <button
              type="button"
              disabled={regionalWebSeriesLoading || page <= 1 || !canNavigate}
              onClick={() => navigate(page - 1)}
              className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-semibold text-slate-300 disabled:opacity-40"
            >
              Previous
            </button>
            <span className="text-xs text-slate-500">Page {page} of {totalPages.toLocaleString()}</span>
            <button
              type="button"
              disabled={regionalWebSeriesLoading || page >= totalPages || !canNavigate}
              onClick={() => navigate(page + 1)}
              className="rounded-lg bg-cyan-500 px-3 py-2 text-xs font-bold text-slate-950 disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </>
      )}

      {catalogue && catalogue.results.length === 0 && !regionalWebSeriesLoading && (
        <div className="rounded-xl border border-slate-800 bg-slate-900 px-4 py-5 text-sm text-slate-400">
          No series were found on this page. Try another subsection or page.
        </div>
      )}
    </section>
  );
}
