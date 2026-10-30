import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { build } from 'esbuild';

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const repositoryRoot = resolve(frontendRoot, '..');

async function loadTypeScriptModule(filePath) {
  const { outputFiles } = await build({
    entryPoints: [filePath],
    bundle: true,
    format: 'esm',
    platform: 'node',
    target: 'node20',
    write: false,
  });
  const source = Buffer.from(outputFiles[0].contents).toString('base64');
  return import(`data:text/javascript;base64,${source}`);
}

const [sectionCache, grouping] = await Promise.all([
  loadTypeScriptModule(resolve(frontendRoot, 'src/api/sectionCache.ts')),
  loadTypeScriptModule(resolve(frontendRoot, 'src/components/torrent-search/grouping.ts')),
]);

const catalogues = [
  { mode: 'marvel', section: 'marvel', subsection: 'movies', records: 96 },
  { mode: 'dc-live-action', section: 'dc', subsection: 'live-action', records: 44 },
  { mode: 'dc-animated', section: 'dc', subsection: 'animated', records: 59 },
  { mode: 'classics', section: 'favourites', subsection: 'movies', records: 75 },
];

test('franchise movie catalogues load section records through the card-rendering pipeline', async t => {
  const documents = new Map();
  for (const section of new Set(catalogues.map(catalogue => catalogue.section))) {
    const path = resolve(repositoryRoot, 'backend/cache-seed', `${section}.json`);
    documents.set(section, JSON.parse(await readFile(path, 'utf8')));
  }

  for (const catalogue of catalogues) {
    await t.test(`${catalogue.mode} loads ${catalogue.section}.${catalogue.subsection}`, async () => {
      const location = sectionCache.franchiseCatalogueSection(catalogue.mode);
      assert.deepEqual(location, {
        section: catalogue.section,
        subsection: catalogue.subsection,
      });

      const sectionRequests = [];
      const loaded = await sectionCache.franchiseSectionDocumentFromCache(async section => {
        sectionRequests.push(section);
        return documents.get(section);
      }, catalogue.mode);
      assert.ok(loaded, 'mapped franchise mode must use a section document, not a legacy loader');
      assert.deepEqual(sectionRequests, [catalogue.section]);
      assert.equal(loaded.document.metadataSelfContained, true);

      const subsection = loaded.document.subsections[loaded.location.subsection];
      assert.equal(subsection.mediaType, 'movie');
      assert.equal(subsection.results.length, catalogue.records);

      const moviePage = sectionCache.movieCataloguePageFromSection(
        loaded.document,
        catalogue.mode,
        catalogue.subsection,
        1,
      );
      assert.ok(moviePage);
      assert.equal(moviePage.totalResults, catalogue.records);
      assert.equal(moviePage.results.length, 18);

      const rows = sectionCache.franchiseRowsFromSection(
        loaded.document,
        catalogue.subsection,
      );
      assert.ok(rows);
      assert.equal(rows.length, catalogue.records);
      const firstPageRows = rows.slice(0, subsection.pageSize);
      assert.equal(firstPageRows.length, 18);
      assert.ok(firstPageRows.every(row => row.sectionCacheRecord));

      const displayableRows = grouping.filterTorrentSearchResults(firstPageRows, {
        minSizeBytes: 1,
        maxSizeBytes: 1_000_000_000,
        resolutionFilter: null,
      });
      assert.equal(displayableRows.length, 18);
      const uiGroups = grouping.groupTorrentResults(displayableRows);
      assert.equal(uiGroups.length, 18);
      assert.deepEqual(
        uiGroups.map(group => group.variants[0].title),
        firstPageRows.map(row => row.title),
      );
      assert.equal(
        grouping.filterTorrentSearchResults(
          [{ title: 'Unseeded torrent', size: 0, seeders: 0, leechers: 0 }],
          { minSizeBytes: 1, maxSizeBytes: 1_000_000_000, resolutionFilter: null },
        ).length,
        0,
        'torrent eligibility filters must remain active for ordinary search results',
      );
    });
  }
});
