import { useMemo } from 'react';
import { MovieCatalogueItem } from '../../../api/client.ts';
import { compareReleaseDateDescending } from '../grouping.ts';
import { useCatalogueNavigationState } from './useCatalogueNavigationState.ts';

export function useVisibleMovieCatalogue({ movieCatalogue, isMarvelEnglishResults, showMarvelWebSeries, marvelFilmFilter, isDcLiveActionEnglishResults, streamingOnly, ottAvailabilityForMovie, ottAvailability }: Pick<ReturnType<typeof useCatalogueNavigationState>, 'movieCatalogue' | 'isMarvelEnglishResults' | 'showMarvelWebSeries' | 'marvelFilmFilter' | 'isDcLiveActionEnglishResults' | 'streamingOnly' | 'ottAvailabilityForMovie' | 'ottAvailability'>) {
  const visibleMovieCatalogueItems = useMemo(() => {
    let movies = movieCatalogue?.results || [];
    if (isMarvelEnglishResults) {
      movies = movies.filter(movie => {
        const rawTitle = String(movie.title || '');
        const title = rawTitle.replace(/\s*\(?((?:19|20)\d{2})\)?\s*$/, '').trim();
        const year = Number(movie.year || rawTitle.match(/\b(?:19|20)\d{2}\b/)?.[0] || 0);
        return !(year === 1977 && /^(?:the )?amazing spider[- ]?man$/i.test(title));
      });
    }
    if (isMarvelEnglishResults && !showMarvelWebSeries && marvelFilmFilter !== 'all') {
      const titleOf = (movie: MovieCatalogueItem) => String(movie.title || '').replace(/\s*\(?((?:19|20)\d{2})\)?\s*$/, '').trim().toLowerCase();
      const yearOf = (movie: MovieCatalogueItem) => Number(movie.year || String(movie.title || '').match(/\b(?:19|20)\d{2}\b/)?.[0] || 0);
      const mcuTitles = new Set([
        'ant-man','ant-man and the wasp','ant-man and the wasp: quantumania','avengers: age of ultron','avengers: endgame','avengers: infinity war','the avengers',
        'black panther','black panther: wakanda forever','black widow','captain america: brave new world','captain america: civil war',
        'captain america: the first avenger','captain america: the winter soldier','captain marvel','doctor strange',
        'doctor strange in the multiverse of madness','deadpool & wolverine','eternals','the punisher: one last kill','the punisher one last kill','a marvel television special presentation the punisher one last kill','guardians of the galaxy',
        'guardians of the galaxy vol. 2','guardians of the galaxy vol. 3','iron man','iron man 2','iron man 3',
        'shang-chi and the legend of the ten rings','spider-man: brand new day','spider-man: far from home','spider-man: homecoming',
        'spider-man: no way home','the fantastic four: first steps','the incredible hulk','the marvels','thor','thor: love and thunder',
        'thor: ragnarok','thor: the dark world','thunderbolts'
      ]);
      const isSpiderMan = (title: string) => /spider[- ]?man|spider[- ]verse|into the spider|across the spider/i.test(title);
      const isXMen = (title: string) => /x[- ]?men|wolverine|deadpool|new mutants|dark phoenix/i.test(title);
      const isSony = (title: string) => isSpiderMan(title) || /venom|morbius|kraven|madame web/i.test(title);
      movies = movies.filter(movie => {
        const title = titleOf(movie);
        const year = yearOf(movie);
        switch (marvelFilmFilter) {
          case 'mcu': return mcuTitles.has(title) ||
            /^the punisher:?\s+one last kill$/i.test(title) ||
            /^(?:a\s+)?marvel television special presentation:?\s+the punisher:?\s+one last kill$/i.test(title);
          case 'x-men': return isXMen(title);
          case 'sony': return isSony(title);
          default: return true;
        }
      });
    }
    if (isDcLiveActionEnglishResults) {
      movies = movies.filter(movie => !/batman\s*:\s*mask of the phantasm/i.test(String(movie.title || '')));
    }
    // These catalogues already carry their intended source ordering; re-sorting
    // them by release date would discard it.
    const catalogueKey = String(movieCatalogue?.catalogue || '');
    const isRegionalMovieCatalogue = catalogueKey.startsWith('highest-rated-') ||
      /^(popular|trending|latest)-(bollywood|hollywood|korean|pakistani|anime)$/.test(
      catalogueKey,
    );
    if (!isRegionalMovieCatalogue) {
      movies = [...movies].sort(compareReleaseDateDescending);
    }
    if (streamingOnly) movies = movies.filter(movie => ottAvailabilityForMovie(movie)?.status === 'streaming');
    return movies;
  }, [movieCatalogue, streamingOnly, ottAvailability, isMarvelEnglishResults, showMarvelWebSeries, marvelFilmFilter, isDcLiveActionEnglishResults]);
  const ottPendingCount = movieCatalogue?.results.filter(movie => {
    const status = ottAvailabilityForMovie(movie)?.status;
    return !status || status === 'loading';
  }).length || 0;

  return {
    visibleMovieCatalogueItems,
    ottPendingCount,
  };
}
