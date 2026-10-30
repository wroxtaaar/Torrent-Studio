import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');

test('franchise movie grid has matching pagination bars above and below its cards', async () => {
  const [resultsSource, panelSource] = await Promise.all([
    readFile(resolve(frontendRoot, 'src/components/torrent-search/sections/SearchResultsSection.tsx'), 'utf8'),
    readFile(resolve(frontendRoot, 'src/components/torrent-search/useTorrentSearchPanel.tsx'), 'utf8'),
  ]);
  const call = '{!isSearching && renderFranchisePagination(Math.max(groupedResults.length, catalogueExpectedTitles))}';
  const positions = [...resultsSource.matchAll(new RegExp(call.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g'))]
    .map(match => match.index);
  const movieGridClass = resultsSource.indexOf('className="grid grid-cols-2 items-stretch gap-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 lg:rounded-2xl');
  const movieGrid = resultsSource.lastIndexOf('<div', movieGridClass);

  assert.equal(positions.length, 2, 'the top and bottom bars should call the same pagination helper');
  assert.ok(movieGridClass >= 0 && movieGrid >= 0, 'the shared movie-card grid should exist');
  assert.ok(positions[0] < movieGrid, 'the first bar should precede the movie cards');
  assert.equal(resultsSource.slice(positions[0] + call.length, movieGrid).trim(), '');
  assert.ok(positions[1] > movieGrid, 'the second bar should follow the movie cards');

  assert.match(panelSource, /total > franchiseGridPageSize/);
  assert.match(panelSource, /franchiseGridPage <= 1[\s\S]*navigateFranchisePage\(Math\.max\(1, franchiseGridPage - 1\)\)/);
  assert.match(panelSource, /franchiseGridPage >= Math\.ceil\(total \/ franchiseGridPageSize\)[\s\S]*navigateFranchisePage\(Math\.min\(Math\.ceil\(total \/ franchiseGridPageSize\), franchiseGridPage \+ 1\)\)/);
});
