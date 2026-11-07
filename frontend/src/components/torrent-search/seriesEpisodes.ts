export interface TorrentFileInfo { index: number; name: string; size: number; path: string }
export interface EpisodeEntry { file: TorrentFileInfo; season: number; episode: number; label: string }

const VIDEO = /\.(mkv|mp4|m4v|avi|webm|mov|ts)$/i;

/** Season / episode numbers from a release file name: S02E05, 2x05, E05 or "Episode 5". Zero means unknown. */
export function parseEpisode(path: string): { season: number; episode: number } {
  const name = String(path || '').split('/').pop() || '';
  let m = name.match(/s(\d{1,2})[\s._-]*e(\d{1,3})/i) || name.match(/(?:^|[^\d])(\d{1,2})x(\d{2,3})(?!\d)/i);
  if (m) return { season: Number(m[1]), episode: Number(m[2]) };
  m = name.match(/(?:^|[\s._\[(-])e(?:p(?:isode)?)?[\s._-]?(\d{1,3})(?!\d)/i);
  if (m) return { season: 0, episode: Number(m[1]) };
  return { season: 0, episode: 0 };
}

/** Video files of a torrent as an ordered episode list (samples dropped, no-number files last). */
export function episodesOf(files: TorrentFileInfo[]): EpisodeEntry[] {
  return files
    .filter(file => VIDEO.test(file.path || file.name) && !/(^|[\s._\/-])sample([\s._\/-]|$)/i.test(file.path || file.name))
    .map(file => {
      const { season, episode } = parseEpisode(file.path || file.name);
      const base = (file.path || file.name).split('/').pop() || file.name;
      return { file, season, episode, label: episode ? 'E' + String(episode).padStart(2, '0') : base };
    })
    .sort((a, b) => (a.season || 999) - (b.season || 999) || (a.episode || 9999) - (b.episode || 9999) || a.file.path.localeCompare(b.file.path));
}

/** Webtor addresses a file inside a multi-file torrent as /<torrent name>/<path>. */
export function webtorFilePath(torrentName: string, file: TorrentFileInfo, multiFile: boolean): string {
  const path = String(file.path || file.name || '').replace(/^\/+/, '');
  return multiFile && torrentName ? '/' + torrentName + '/' + path : '/' + path;
}
