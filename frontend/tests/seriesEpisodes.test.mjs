import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const out = join(mkdtempSync(join(tmpdir(), 'se-')), 'm.mjs');
execFileSync(join(here, '../node_modules/.bin/esbuild'), [join(here, '../src/components/torrent-search/seriesEpisodes.ts'), '--bundle', '--format=esm', `--outfile=${out}`, '--log-level=error']);
const { parseEpisode, episodesOf, webtorFilePath } = await import(pathToFileURL(out).href);

test('episode numbers are read from common release names', () => {
  assert.deepEqual(parseEpisode('Show.S01E05.2160p.mkv'), { season: 1, episode: 5 });
  assert.deepEqual(parseEpisode('Show/Season 2/Show 2x10 HDTV.mkv'), { season: 2, episode: 10 });
  assert.deepEqual(parseEpisode('[Group] Show - E07 [1080p].mkv'), { season: 0, episode: 7 });
  assert.deepEqual(parseEpisode('Show 1080p x265.mkv'), { season: 0, episode: 0 });
});

test('episode list keeps videos in order and drops samples and extras', () => {
  const files = [
    { index: 0, name: 'b', size: 3, path: 'Show/Show.S01E10.mkv' },
    { index: 1, name: 'b', size: 3, path: 'Show/Show.S01E02.mkv' },
    { index: 2, name: 'b', size: 1, path: 'Show/Sample/sample.mkv' },
    { index: 3, name: 'b', size: 1, path: 'Show/readme.nfo' },
  ];
  assert.deepEqual(episodesOf(files).map(entry => entry.label), ['E02', 'E10']);
});

test('webtor file path includes the torrent name for multi-file torrents', () => {
  assert.equal(webtorFilePath('Show', { path: 'Season 1/a.mkv', name: 'a', size: 1, index: 0 }, true), '/Show/Season 1/a.mkv');
  assert.equal(webtorFilePath('Show', { path: 'Show.mkv', name: 'a', size: 1, index: 0 }, false), '/Show.mkv');
});
