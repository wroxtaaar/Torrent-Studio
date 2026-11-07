import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));

// React error #310 ("rendered more hooks than during the previous render") happens when a hook is called after an early
// return. The player model returns null while no file is open, so every hook must sit above that line.
test('no React hook is called after the early return in the media player model', () => {
  const source = readFileSync(join(here, '../src/components/media-player/useMediaPlayerModel.tsx'), 'utf8');
  const early = source.indexOf('if (!file) return null;');
  assert.ok(early > 0, 'early return not found');
  const after = source.slice(early);
  const hooks = after.match(/\buse(State|Effect|Ref|Memo|Callback|Reducer|LayoutEffect|Id|SyncExternalStore)\s*\(/g) || [];
  assert.deepEqual(hooks, [], `hooks after the early return: ${hooks.join(', ')}`);
});
