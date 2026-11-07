import React from 'react';
import { currentPlatform, mxPlayerLink, vlcLink } from '../torrent-search/hdPlayer.ts';

const chip = 'inline-flex items-center gap-1 whitespace-nowrap rounded-lg border border-slate-700/80 bg-slate-800/80 px-2.5 py-2 text-[11px] font-bold text-slate-200 transition hover:bg-slate-700';

/**
 * Hands the original file to VLC or MX Player (Android only), which list every audio track and subtitle and play
 * formats the browser cannot. The link is the file's download address, which redirects to Seedr's own file URL, so the
 * video does not pass through this server.
 */
export const ExternalPlayerButtons: React.FC<{ url: string; className?: string }> = ({ url, className }) => {
  const absolute = (() => {
    try { return new URL(url, typeof window === 'undefined' ? undefined : window.location.href).href; } catch { return ''; }
  })();
  const platform = currentPlatform();
  const vlc = absolute ? vlcLink(absolute, platform) : '';
  const mx = absolute ? mxPlayerLink(absolute, platform) : '';
  if (!vlc && !mx) return null;
  return (
    <div className={'flex items-center gap-1.5 ' + (className || '')}>
      {vlc && <a href={vlc} title="Open in VLC (all audio tracks and subtitles)" aria-label="Open in VLC" className={chip}>VLC</a>}
      {mx && <a href={mx} title="Open in MX Player (all audio tracks and subtitles)" aria-label="Open in MX Player" className={chip}>MX Player</a>}
    </div>
  );
};
