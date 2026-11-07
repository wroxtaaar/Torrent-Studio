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
