import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { build, transform } from 'esbuild';

const root = new URL('../', import.meta.url);
const sectionCachePath = fileURLToPath(new URL('src/api/sectionCache.ts', root));
const sectionCacheSource = await readFile(sectionCachePath, 'utf8');
const transformed = await transform(sectionCacheSource, { loader: 'ts', format: 'esm' });
const sectionCache = await import(`data:text/javascript;base64,${Buffer.from(transformed.code).toString('base64')}`);
const searchPath = fileURLToPath(new URL('src/api/search.ts', root));
const bundledSearch = await build({
  entryPoints: [searchPath],
  bundle: true,
  format: 'esm',
  platform: 'node',
  write: false,
  define: { 'import.meta.env': '{}' },
});
const searchApi = await import(
  `data:text/javascript;base64,${Buffer.from(bundledSearch.outputFiles[0].text).toString('base64')}`
);

test('DC Web Series pages use all 40 curated section records without duplicates', async t => {
  const document = JSON.parse(await readFile(
    new URL('../../backend/cache-seed/dc.json', import.meta.url),
    'utf8',
  ));
  const allShows = document.subsections.series.results;
  assert.equal(document.subsections.series.mediaType, 'tv');
  assert.equal(allShows.length, 40);

  const requests = [];
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = async input => {
    requests.push(String(input));
    return new Response(JSON.stringify(document), { status: 200 });
  };
  const loadPage = page => sectionCache.tvCataloguePageFromSectionCache(
    section => searchApi.searchApi.getSectionCache(section),
    'dc-live-action',
    page,
  );

  const pages = [await loadPage(1), await loadPage(2), await loadPage(3)];
  assert.deepEqual(pages.map(page => page.results.length), [18, 18, 4]);
  assert.deepEqual(
    pages.flatMap(page => page.results).map(show => String(show.id)),
    allShows.map(show => String(show.tmdbId ?? show.id)),
  );
  assert.equal(new Set(pages.flatMap(page => page.results).map(show => String(show.id))).size, 40);
  assert.ok(pages.every(page => page.totalPages === 3 && page.totalResults === 40));
  assert.equal(requests.length, 1, 'subsequent pages reuse the same fetched section document');
  assert.match(requests[0], /\/api\/sections\/dc$/);
  assert.equal(requests.some(url => url.includes('/api/tv/catalogue/')), false);
});

test('DC Web Series UI uses one section-backed pagination system above and below the grid', async () => {
  const resultsPath = fileURLToPath(new URL('src/components/torrent-search/sections/SearchResultsSection.tsx', root));
  const loaderPath = fileURLToPath(new URL('src/components/torrent-search/state/useWebSeriesLoaders.ts', root));
  const [resultsSource, loaderSource] = await Promise.all([
    readFile(resultsPath, 'utf8'),
    readFile(loaderPath, 'utf8'),
  ]);
  const start = resultsSource.indexOf(') : showDcWebSeries ? (');
  const end = resultsSource.indexOf(') : showMarvelWebSeries ? (', start);
  const branch = resultsSource.slice(start, end);
  const paginationHelper = resultsSource.slice(0, start);

  assert.ok(start >= 0 && end > start);
  assert.equal((branch.match(/renderDcWebSeriesPagination\(\)/g) || []).length, 2);
  assert.match(branch, /dcWebSeriesCatalogue\.results\.map/);
  assert.match(paginationHelper, /loadDcWebSeriesPage\(page - 1\)/);
  assert.match(paginationHelper, /loadDcWebSeriesPage\(page \+ 1\)/);
  assert.doesNotMatch(branch, /Load More/i);
  assert.match(loaderSource, /loadTvCataloguePage\('dc-live-action', page\)/);
  assert.match(loaderSource, /setFranchiseGridPage\(1\)/);
  assert.match(loaderSource, /setResults\(\[\]\)/);
  assert.doesNotMatch(loaderSource, /setDcWebSeriesCatalogue\(.*results:\s*\[/);
});
