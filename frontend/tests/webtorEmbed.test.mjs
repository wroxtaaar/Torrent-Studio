import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
async function bundle(rel) {
  const out = join(mkdtempSync(join(tmpdir(), 'we-')), 'm.mjs');
  execFileSync(join(here, '../node_modules/.bin/esbuild'), [join(here, rel), '--bundle', '--format=esm', `--outfile=${out}`, '--log-level=error']);
  return import(pathToFileURL(out).href);
}

test('webtor embed config only accepts magnet links', async () => {
  const { webtorEmbedConfig, WEBTOR_SDK_URL } = await bundle('../src/components/torrent-search/webtor.ts');
  const config = webtorEmbedConfig('player-1', 'magnet:?xt=urn:btih:abc&dn=Film', 'Film');
  assert.equal(config.id, 'player-1');
  assert.equal(config.magnet, 'magnet:?xt=urn:btih:abc&dn=Film');
  assert.equal(config.title, 'Film');
  assert.equal(webtorEmbedConfig('p', 'https://example.com/a.torrent'), null);
  assert.equal(webtorEmbedConfig('p', ''), null);
  assert.equal(webtorEmbedConfig('p', undefined), null);
  assert.match(WEBTOR_SDK_URL, /^https:\/\/cdn\.jsdelivr\.net\/npm\/@webtor\/embed-sdk-js@?[^/]*\/?dist\/index\.min\.js$|^https:\/\/cdn\.jsdelivr\.net\/npm\/@webtor\/embed-sdk-js\/dist\/index\.min\.js$/);
});

test('info hash and Webtor page link from magnets', async () => {
  const { magnetInfoHash, webtorTorrentPageUrl } = await bundle('../src/components/torrent-search/webtor.ts');
  const hex = 'cfb5e3e51ed4eaf575f5e19bcdf991645a8c997a';
  assert.equal(magnetInfoHash(`magnet:?xt=urn:btih:${hex.toUpperCase()}&dn=Kraven`), hex);
  assert.equal(webtorTorrentPageUrl(`magnet:?dn=x&xt=urn:btih:${hex}&tr=udp://t`), `https://webtor.io/${hex}`);
  // the same hash written in base32 gives the same hex
  const bytes = hex.match(/../g).map(pair => parseInt(pair, 16));
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  let bits = bytes.map(byte => byte.toString(2).padStart(8, '0')).join('');
  let base32 = '';
  for (let index = 0; index < bits.length; index += 5) base32 += alphabet[parseInt(bits.slice(index, index + 5), 2)];
  assert.equal(magnetInfoHash(`magnet:?xt=urn:btih:${base32}`), hex);
  assert.equal(magnetInfoHash('magnet:?dn=nothing'), '');
  assert.equal(webtorTorrentPageUrl('https://example.com/a.torrent'), '');
});
