// Movie card drop-downs: best resolution first, then bigger files; releases nobody is seeding are hidden.
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { build } from 'esbuild';

const bundle = async entry => {
  const result = await build({ entryPoints: [fileURLToPath(new URL(entry, import.meta.url))], bundle: true, format: 'esm', platform: 'node', write: false, define: { 'import.meta.env': '{}' } });
  return import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`);
};
const { orderTorrents, orderHdOptions } = await bundle('../src/components/torrent-search/actionOrdering.ts');
const GB = 1024 ** 3;
const row = (title, size, seeders) => ({ title, size, seeders, infoHash: title });

test('torrents: zero-seed releases never appear', () => {
  const rows = orderTorrents([row('A 1080p', 2 * GB, 0), row('B 1080p', 1 * GB, 3), row('C 720p', 1 * GB, undefined)]);
  assert.deepEqual(rows.map(r => r.title), ['B 1080p']);
});

test('torrents: resolution descending, then size descending', () => {
  const rows = orderTorrents([
    row('M 720p', 4 * GB, 5), row('N 1080p BluRay', 2 * GB, 5), row('O 2160p', 9 * GB, 5),
    row('P 1080p WEB-DL', 5 * GB, 5), row('Q 720p', 1 * GB, 5), row('R 1080p', 3 * GB, 5),
  ]);
  assert.deepEqual(rows.map(r => r.title), ['O 2160p', 'P 1080p WEB-DL', 'R 1080p', 'N 1080p BluRay', 'M 720p', 'Q 720p']);
});

test('HD options: 4K, 1080p, 720p, other; bigger first inside a quality; input is not mutated', () => {
  const input = [
    { key: '0', quality: '1080p', size: 2 * GB }, { key: '1', quality: 'other', size: 9 * GB },
    { key: '2', quality: '2160p', size: 4 * GB }, { key: '3', quality: '1080p', size: 10 * GB }, { key: '4', quality: '720p', size: 1 * GB },
  ];
  assert.deepEqual(orderHdOptions(input).map(o => o.key), ['2', '3', '0', '4', '1']);
  assert.deepEqual(input.map(o => o.key), ['0', '1', '2', '3', '4']);
});
