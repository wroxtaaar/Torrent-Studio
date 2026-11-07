// Play HD: platform detection and the VLC / MX Player links.
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { build } from 'esbuild';

const bundle = async entry => {
  const result = await build({ entryPoints: [fileURLToPath(new URL(entry, import.meta.url))], bundle: true, format: 'esm', platform: 'node', write: false });
  return import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`);
};
const { platformFromUserAgent, vlcLink, mxPlayerLink, androidIntent, playsSilently } = await bundle('../src/components/torrent-search/hdPlayer.ts');
const url = 'https://a.workers.dev/tok::1/The%20Film%20%5BHindi%5D.mkv';

test('platform detection: Android, iPhone, iPadOS (Mac UA with touch), desktop', () => {
  assert.equal(platformFromUserAgent('Mozilla/5.0 (Linux; Android 14; Pixel 8) Chrome/120'), 'android');
  assert.equal(platformFromUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)'), 'ios');
  assert.equal(platformFromUserAgent('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)', 5), 'ios');
  assert.equal(platformFromUserAgent('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)', 0), 'desktop');
  assert.equal(platformFromUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120'), 'desktop');
});

test('Android links are intents for the app package; the https scheme is moved into the intent', () => {
  assert.equal(androidIntent(url, 'org.videolan.vlc'), 'intent://a.workers.dev/tok::1/The%20Film%20%5BHindi%5D.mkv#Intent;scheme=https;package=org.videolan.vlc;type=video/*;end');
  assert.match(mxPlayerLink(url, 'android'), /package=com\.mxtech\.videoplayer\.ad;/);
  assert.match(vlcLink(url, 'android'), /package=org\.videolan\.vlc;/);
});

test('iOS and desktop VLC links; MX Player only on Android', () => {
  assert.equal(vlcLink(url, 'ios'), 'vlc-x-callback://x-callback-url/stream?url=' + encodeURIComponent(url));
  assert.equal(vlcLink(url, 'desktop'), 'vlc://' + url);
  assert.equal(mxPlayerLink(url, 'ios'), '');
  assert.equal(mxPlayerLink(url, 'desktop'), '');
});

test('only http(s) links are handed to other apps', () => {
  assert.match(vlcLink('http://plain.example/x.mkv', 'android'), /^intent:\/\/plain\.example\/x\.mkv#Intent;scheme=http;package=org\.videolan\.vlc;/);
  assert.equal(vlcLink('ftp://plain.example/x.mkv', 'android'), '');
  assert.equal(mxPlayerLink('file:///x', 'android'), '');
});

test('silent playback is detected only when the browser reports zero decoded audio after the start', () => {
  assert.equal(playsSilently({ currentTime: 5, muted: false, webkitAudioDecodedByteCount: 0 }), true);
  assert.equal(playsSilently({ currentTime: 5, muted: false, webkitAudioDecodedByteCount: 4096 }), false);
  assert.equal(playsSilently({ currentTime: 1, muted: false, webkitAudioDecodedByteCount: 0 }), false, 'too early to tell');
  assert.equal(playsSilently({ currentTime: 5, muted: true, webkitAudioDecodedByteCount: 0 }), false, 'muted by the user');
  assert.equal(playsSilently({ currentTime: 5, muted: false }), false, 'unknown browsers count as having sound');
  assert.equal(playsSilently({ currentTime: 5, muted: false, mozHasAudio: false }), true);
});

test('audio tracks advertised by a release name', async () => {
  const { audioFromFilename, browserAudioTracks } = await bundle('../src/components/torrent-search/hdPlayer.ts');
  const dual = audioFromFilename('The Shawshank Redemption (1994) 1080p BluRay [Hindi DDP 2.0 + English DTS-HDMA 5.1] x264 (Hallowed-4kHdHub.com).mkv');
  assert.deepEqual(dual.map(track => track.label), ['Hindi (DDP 2.0)', 'English (DTS-HDMA 5.1)']);
  assert.deepEqual(audioFromFilename('Film 2160p [Hindi NF HE-AAC 2.0 128kbps + English AAC 5.1] ESub.mkv').map(track => track.language), ['Hindi', 'English']);
  assert.deepEqual(audioFromFilename('Film (1994) 1080p BluRay REMUX AVC (UnKn0wn-4kHdHub.com).mkv'), [], 'no audio group in the name');
  assert.deepEqual(audioFromFilename('Film [1080p] [x264] (2020).mkv'), [], 'brackets that are not audio are ignored');
  assert.deepEqual(audioFromFilename(''), []);
  assert.deepEqual(browserAudioTracks({}), [], 'browsers without audioTracks');
  const two = browserAudioTracks({ audioTracks: { length: 2, 0: { id: 'a', label: 'English', language: 'en', enabled: true }, 1: { id: 'b', label: '', language: 'hi', enabled: false } } });
  assert.deepEqual(two.map(track => [track.id, track.enabled]), [['a', true], ['b', false]]);
});

test('MX Player and VLC links accept the app\'s own (http or https) file address', async () => {
  const url = 'http://129.154.242.170:3000/api/seedr/files/55/download';
  assert.equal(mxPlayerLink(url, 'android'), 'intent://129.154.242.170:3000/api/seedr/files/55/download#Intent;scheme=http;package=com.mxtech.videoplayer.ad;type=video/*;end');
  assert.equal(mxPlayerLink(url, 'desktop'), '', 'MX Player is Android only');
});

test('release names with Dolby Digital Plus / DTS audio are flagged for MX Player', async () => {
  const { hasHeavyAudio } = await bundle('../src/components/torrent-search/hdPlayer.ts');
  assert.equal(hasHeavyAudio('Oppenheimer (2023) IMAX 1080p BluRay [Hindi DDP 5.1 + English DTS-HDMA 5.1] x265.mkv'), true);
  assert.equal(hasHeavyAudio('Film 2160p WEB-DL DDP5.1 Atmos x265.mkv'), true);
  assert.equal(hasHeavyAudio('Film 1080p BluRay TrueHD 7.1.mkv'), true);
  assert.equal(hasHeavyAudio('Film 1080p BluRay AAC 5.1 x264.mkv'), false);
  assert.equal(hasHeavyAudio('Odds and Ends (2020) 1080p.mkv'), false, 'no false positive inside other words');
  assert.equal(hasHeavyAudio(''), false);
});
