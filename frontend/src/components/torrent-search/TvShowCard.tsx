import React from 'react';
import type { TvCatalogueItem } from '../../api/client.ts';
import { MovieCompactCard, imdbTitleLink, type MovieCardImdb } from '../MovieCards.tsx';
import { toCardProviders, uniqueOttProviders } from './ottProviders.ts';
import { lowQualityPosterUrl } from './posterUrls.ts';

type TvShowCardShow = Pick<TvCatalogueItem, 'id' | 'title' | 'year' | 'posterUrl' | 'overview' | 'rating' | 'streamingProviders'>;

/**
 * The initial card for every TV / web-series section. It is the same MovieCompactCard the
 * movie sections use, so a change to that card applies to movies and series alike; this
 * wrapper only maps a series to the card's props. Clicking the card runs `onOpen`.
 */
export const TvShowCard: React.FC<{
  show: TvShowCardShow;
  imdb?: MovieCardImdb;
  onOpen: () => void;
  /** Optional action area at the bottom of the card. */
  footer?: React.ReactNode;
}> = ({ show, imdb, onOpen, footer }) => {
  const providers = uniqueOttProviders(
    (show.streamingProviders || []).filter(provider => ['subscription', 'free', 'ads'].includes(provider.type)),
  );
  return (
    <MovieCompactCard
      title={show.title}
      titleHref={imdbTitleLink(imdb, show.title, show.year)}
      year={show.year}
      imdb={imdb}
      tmdbRating={show.rating}
      overview={show.overview || ''}
      posterSrc={show.posterUrl ? lowQualityPosterUrl(show.posterUrl) : ''}
      posterAlt={show.title}
      onPosterClick={onOpen}
      onPosterLoad={() => {}}
      onPosterError={event => {
        const image = event.currentTarget;
        if (image.src.includes('/t/p/w780/')) {
          image.src = image.src.replace('/t/p/w780/', '/t/p/w185/');
          return;
        }
        // TMDB can return a stale/missing poster path. Retry through the same-origin
        // title/year poster resolver before showing a blank card.
        if (image.dataset.posterFallbackTried !== 'true') {
          image.dataset.posterFallbackTried = 'true';
          const params = new URLSearchParams({ title: show.title, size: 'w185' });
          if (show.year) params.set('year', String(show.year));
          image.src = '/api/poster?' + params.toString();
          return;
        }
        image.style.display = 'none';
      }}
      providers={toCardProviders(providers)}
      providersAriaLabel={'Streaming services for ' + show.title}
      providersFallbackText="Streaming providers not listed"
      footer={footer}
    />
  );
};
