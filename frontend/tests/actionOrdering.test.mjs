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

test('merged torrent list: best resolution first, then size, regardless of source', async () => {
  const { mergeByOrder } = await bundle('../src/components/torrent-search/actionOrdering.ts');
  const seedr = [{ key: 's1', order: 3e13 + 1.5e9 }, { key: 's2', order: 2e13 + 1e9 }];
  const webtor = [{ key: 'w1', order: 4e13 + 9e9 }, { key: 'w2', order: 3e13 + 4e9 }, { key: 'w3' }];
  assert.deepEqual(mergeByOrder(seedr, webtor).map(item => item.key), ['w1', 'w2', 's1', 's2', 'w3']);
  assert.deepEqual(mergeByOrder([], []), []);
});

test('resolution buttons: buckets and source tags', async () => {
  const { resolutionBucket, formatLabelOf } = await bundle('../src/components/torrent-search/actionOrdering.ts');
  const row = title => ({ title, quality: '', size: 1e9, seeders: 5, magnetUrl: 'magnet:?xt=urn:btih:a' });
  assert.equal(resolutionBucket(row('Film 2024 2160p BluRay')), '4k');
  assert.equal(resolutionBucket(row('Film 2024 4K WEB-DL')), '4k');
  assert.equal(resolutionBucket(row('Film 2024 1080p WEBRip')), '1080p');
  assert.equal(resolutionBucket(row('Film 2024 1440p')), '1080p');
  assert.equal(resolutionBucket(row('Film 2024 720p HDTV')), '720p');
  assert.equal(resolutionBucket(row('Film 2024 480p DVDRip')), '720p', 'lower resolutions share the 720p button');
  assert.equal(resolutionBucket(row('Film 2024 Some Release')), 'other');
  assert.equal(formatLabelOf('2160P BluRay'), 'BluRay');
  assert.equal(formatLabelOf('2160P (4K) WEB-DL'), 'WEB-DL');
  assert.equal(formatLabelOf('1080P'), 'Release');
  assert.equal(formatLabelOf('Other release'), 'Release');
});

test('Nuvio files share the resolution buckets and sort values with torrents', async () => {
  const { nuvioBucket, nuvioOrderValue, mergeByOrder, torrentOrderValue } = await bundle('../src/components/torrent-search/actionOrdering.ts');
  assert.equal(nuvioBucket('2160p'), '4k');
  assert.equal(nuvioBucket('1080p'), '1080p');
  assert.equal(nuvioBucket('720p'), '720p');
  assert.equal(nuvioBucket('480p'), '720p');
  assert.equal(nuvioBucket('other'), 'other');
  const file = { key: 'a', quality: '1080p', size: 4e9 };
  const torrent = { title: 'Film 2024 1080p BluRay', quality: '', size: 2e9, seeders: 5 };
  assert.ok(nuvioOrderValue(file) > torrentOrderValue(torrent), 'same resolution: the bigger file first');
  assert.equal(nuvioOrderValue({ key: 'b', quality: '2160p', size: 1 }) > nuvioOrderValue(file), true, '4K above 1080p');
  const merged = mergeByOrder([{ k: 'n', order: nuvioOrderValue(file) }], [{ k: 't', order: torrentOrderValue(torrent) }]);
  assert.deepEqual(merged.map(item => item.k), ['n', 't']);
});
