import { useMemo } from 'react';
import { MovieCatalogueItem } from '../../../api/client.ts';
import { compareReleaseDateDescending, imdbRatingKey, releaseDateSortValue } from '../grouping.ts';
import { ClassicsSort, classicsComparator, isDefaultClassicsSort, ratingValue } from '../classicsSort.ts';

export const REGIONAL_CATALOGUE_PATTERN = /^(popular|trending|latest)-(bollywood|hollywood)$/;
export const REGIONAL_CACHED_PAGES = 3;
export const REGIONAL_PAGE_SIZE = 18;
import { useCatalogueNavigationState } from './useCatalogueNavigationState.ts';

export function useVisibleMovieCatalogue({ movieCatalogue, isMarvelEnglishResults, showMarvelWebSeries, marvelFilmFilter, isDcLiveActionEnglishResults, streamingOnly, ottAvailabilityForMovie, ottAvailability, classicsSort, regionalPool, imdbRatingsByKey }: { classicsSort: ClassicsSort; regionalPool: MovieCatalogueItem[]; imdbRatingsByKey: Record<string, { imdbRating?: number | string | null } | undefined> } & Pick<ReturnType<typeof useCatalogueNavigationState>, 'movieCatalogue' | 'isMarvelEnglishResults' | 'showMarvelWebSeries' | 'marvelFilmFilter' | 'isDcLiveActionEnglishResults' | 'streamingOnly' | 'ottAvailabilityForMovie' | 'ottAvailability'>) {
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
    // Regional catalogues arrive pre-sorted by popularity, release date, or
    // weekly trend history; re-sorting them by release date would discard that ranking.
    const isRegionalMovieCatalogue = /^(popular|trending|latest)-(bollywood|hollywood)$/.test(
      String(movieCatalogue?.catalogue || ''),
    );
    if (!isRegionalMovieCatalogue) {
      movies = [...movies].sort(compareReleaseDateDescending);
    } else if (!isDefaultClassicsSort(classicsSort) && regionalPool.length && Number(movieCatalogue?.page || 1) <= REGIONAL_CACHED_PAGES) {
      // Section-wide sort over the cached pages (54 titles): sort the whole pool, then show this page's slice.
      const page = Number(movieCatalogue?.page || 1);
      const sortedPool = [...regionalPool].sort(classicsComparator(
        classicsSort,
        movie => releaseDateSortValue(movie),
        movie => ratingValue(imdbRatingsByKey[imdbRatingKey(movie.title, movie.year)]) ?? ratingValue(movie),
        movie => String(movie.title || ''),
      ));
      movies = sortedPool.slice((page - 1) * REGIONAL_PAGE_SIZE, page * REGIONAL_PAGE_SIZE);
    }
    if (streamingOnly) movies = movies.filter(movie => ottAvailabilityForMovie(movie)?.status === 'streaming');
    return movies;
  }, [movieCatalogue, streamingOnly, ottAvailability, isMarvelEnglishResults, showMarvelWebSeries, marvelFilmFilter, isDcLiveActionEnglishResults, classicsSort.key, classicsSort.direction, regionalPool, imdbRatingsByKey]);
  const ottPendingCount = movieCatalogue?.results.filter(movie => {
    const status = ottAvailabilityForMovie(movie)?.status;
    return !status || status === 'loading';
  }).length || 0;

  return {
    visibleMovieCatalogueItems,
    ottPendingCount,
  };
}
