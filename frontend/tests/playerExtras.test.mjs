import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
async function bundle(rel) {
  const out = join(mkdtempSync(join(tmpdir(), 'pe-')), 'm.mjs');
  execFileSync(join(here, '../node_modules/.bin/esbuild'), [join(here, rel), '--bundle', '--format=esm', `--outfile=${out}`, '--log-level=error']);
  return import(pathToFileURL(out).href);
}

test('resume position is remembered, ignored at the edges', async () => {
  const { loadResume, saveResume, resumeKey } = await bundle('../src/components/media-player/playerExtras.ts');
  const data = new Map();
  const storage = { getItem: k => data.get(k) ?? null, setItem: (k, v) => data.set(k, v), removeItem: k => data.delete(k) };
  const key = resumeKey({ id: '42', name: 'a.mkv' });
  assert.equal(key, 'ts-resume:42');
  saveResume(key, 1234.9, 7000, storage);
  assert.equal(loadResume(key, 7000, storage), 1234);
  saveResume(key, 5, 7000, storage);
  assert.equal(loadResume(key, 7000, storage), 0, 'too early to remember');
  saveResume(key, 1234, 7000, storage);
  saveResume(key, 6990, 7000, storage);
  assert.equal(loadResume(key, 7000, storage), 0, 'finished films start over');
  assert.equal(loadResume('', 7000, storage), 0);
  assert.equal(loadResume(key, 7000, null), 0, 'storage unavailable');
});

test('keyboard shortcuts and tap zones', async () => {
  const { shortcutForKey, tapZone } = await bundle('../src/components/media-player/playerExtras.ts');
  assert.deepEqual(shortcutForKey(' '), { type: 'toggle' });
  assert.deepEqual(shortcutForKey('ArrowLeft'), { type: 'seek', seconds: -5 });
  assert.deepEqual(shortcutForKey('l'), { type: 'seek', seconds: 10 });
  assert.deepEqual(shortcutForKey('5'), { type: 'jump', fraction: 0.5 });
  assert.equal(shortcutForKey('c', {}), null);
  assert.equal(shortcutForKey('f', { ctrl: true }), null, 'browser shortcuts stay untouched');
  assert.equal(tapZone(10, 300), 'back');
  assert.equal(tapZone(290, 300), 'forward');
  assert.equal(tapZone(150, 300), 'center');
  assert.equal(tapZone(1, 0), 'center');
});

test('player preferences, buffered range and seek bar gradient', async () => {
  const { loadPrefs, savePrefs, bufferedEnd, seekGradient } = await bundle('../src/components/media-player/playerExtras.ts');
  const data = new Map();
  const storage = { getItem: k => data.get(k) ?? null, setItem: (k, v) => data.set(k, v), removeItem: k => data.delete(k) };
  assert.deepEqual(loadPrefs(storage), { volume: 1, speed: 1 });
  savePrefs({ volume: 0.4 }, storage);
  savePrefs({ speed: 1.5 }, storage);
  assert.deepEqual(loadPrefs(storage), { volume: 0.4, speed: 1.5 });
  data.set('ts-player-prefs', '{"volume": 9, "speed": 99}');
  assert.deepEqual(loadPrefs(storage), { volume: 1, speed: 1 }, 'out-of-range values fall back');
  data.set('ts-player-prefs', 'not json');
  assert.deepEqual(loadPrefs(storage), { volume: 1, speed: 1 });
  assert.deepEqual(loadPrefs(null), { volume: 1, speed: 1 });
  const ranges = { length: 2, start: i => [0, 100][i], end: i => [50, 180][i] };
  assert.equal(bufferedEnd(ranges, 30), 50);
  assert.equal(bufferedEnd(ranges, 120), 180);
  assert.equal(bufferedEnd(ranges, 70), 0, 'playhead in a gap');
  assert.equal(bufferedEnd(null, 5), 0);
  assert.equal(seekGradient(10, 20, 0), '');
  assert.match(seekGradient(25, 50, 100), /#22d3ee 25%.*#64748b 50%/);
});
