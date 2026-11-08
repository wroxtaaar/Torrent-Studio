import React, { useState, useSyncExternalStore } from 'react';
import { api } from '../../api/client.ts';
import type { TvCatalogueItem } from '../../api/client.ts';
import { MoviePrepareCard, imdbTitleLink, type MovieCardImdb } from '../MovieCards.tsx';
import { torrentQualityDetails } from './grouping.ts';
import { toCardProviders } from './ottProviders.ts';
import { lowQualityPosterUrl } from './posterUrls.ts';
import { TvShowCard, tvCardModel, tvPosterErrorHandler } from './TvShowCard.tsx';
import { createTvTorrentStore, packScopeLabel, tvShowKey } from './tvTorrentStore.ts';
import { WebtorPlayerModal } from '../WebtorPlayerModal.tsx';
import { openWebtorDownload } from './webtor.ts';
import { TvSeasonActions } from './TvSeasonActions.tsx';
import { SeriesPopup } from './SeriesPopup.tsx';
import type { TorrentSearchResult } from '../../api/types.ts';

// One store for the whole app: one open series card at a time, lookups cached for the session.
// The lookup runs only from a card tap (see tvTorrentStore.open), never on page load or paging.
const tvTorrents = createTvTorrentStore(show =>
  api.getTorrentOptions({ tmdbId: show.id, title: show.title, year: show.year }, undefined, 'all', 'tv'));

type TileShow = Pick<TvCatalogueItem, 'id' | 'title' | 'year' | 'releaseDate' | 'posterUrl' | 'overview' | 'rating' | 'streamingProviders' | 'imdbRating' | 'imdbVotes' | 'imdbId' | 'imdbUrl'>;

/**
 * Series card for every TV / web-series grid. Tapping it looks up the cached season packs:
 * with packs it opens the second card (Play = the existing player flow, Webtor = copy the
 * selected magnet and open Webtor); without packs it plays straight away, as before.
 */
export const TvShowTile: React.FC<{
  show: TileShow;
  imdb?: MovieCardImdb;
  /** The existing playback action for this series (NexStream / VidRift, or Yenime for anime). */
  onPlay: () => void;
}> = ({ show, imdb, onPlay }) => {
  const openKey = useSyncExternalStore(tvTorrents.subscribe, tvTorrents.getOpenKey, tvTorrents.getOpenKey);
  const [webtorRow, setWebtorRow] = useState<TorrentSearchResult | null>(null);
  const [webtorPath, setWebtorPath] = useState('');
  const [webtorLabel, setWebtorLabel] = useState('');
  const [browseOpen, setBrowseOpen] = useState(false);
  const open = () => tvTorrents.open(show, onPlay);
  if (openKey !== tvShowKey(show)) return <TvShowCard show={show} imdb={imdb} onOpen={open} />;

  const releases = tvTorrents.releasesFor(show);
  const { rating, displayYear, providers } = tvCardModel(show, imdb);
  return (
    <>
    <MoviePrepareCard
      posterSrc={show.posterUrl ? lowQualityPosterUrl(show.posterUrl) : ''}
      posterAlt={show.title}
      onPosterClick={tvTorrents.close}
      onPosterLoad={() => {}}
      onPosterError={tvPosterErrorHandler(show.title, displayYear)}
      imdb={rating}
      title={show.title}
      titleHref={imdbTitleLink(rating, show.title, displayYear)}
      year={displayYear}
      onClose={tvTorrents.close}
      variants={[]}
      selectedVariantKey=""
      onSelectVariant={() => {}}
      variantsAriaLabel={`Seasons and quality for ${show.title}`}
      prepared={null}
      actions={releases.length > 0 ? (
        <TvSeasonActions releases={releases} onPlay={onPlay} onBrowse={() => setBrowseOpen(true)}
          onWebtorDownload={row => { openWebtorDownload(String(row.magnetUrl)); }} />
      ) : undefined}
      directStream={{ label: 'Play', disabled: false, onClick: onPlay }}
    />
    {browseOpen && (
      <SeriesPopup title={show.title} year={displayYear} posterSrc={show.posterUrl ? lowQualityPosterUrl(show.posterUrl) : ''} releases={releases}
        onClose={() => setBrowseOpen(false)}
        onPlayEpisode={(pack, path, label) => { setWebtorPath(path); setWebtorLabel(label); setWebtorRow(pack); }} />
    )}
    {webtorRow?.magnetUrl && (
      <WebtorPlayerModal title={show.title} magnetUrl={String(webtorRow.magnetUrl)} path={webtorPath || undefined}
        label={webtorLabel || `${packScopeLabel(webtorRow)} · ${torrentQualityDetails(webtorRow).label || ''}`.trim()} onClose={() => setWebtorRow(null)} />
    )}
    </>
  );
};
