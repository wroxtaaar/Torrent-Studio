// Sorting for the Classics section: by release year/date or by IMDb rating.
export type ClassicsSortKey = 'year' | 'rating';
export type ClassicsSortDirection = 'desc' | 'asc';
export interface ClassicsSort {
  key: ClassicsSortKey;
  direction: ClassicsSortDirection;
}

// Both sorts start newest-first / highest-first.
export const DEFAULT_CLASSICS_SORT: ClassicsSort = { key: 'year', direction: 'desc' };

export const isDefaultClassicsSort = (sort: ClassicsSort): boolean =>
  sort.key === DEFAULT_CLASSICS_SORT.key && sort.direction === DEFAULT_CLASSICS_SORT.direction;

/** Pressing the active button flips its direction; pressing the other one selects it, descending. */
export function nextClassicsSort(current: ClassicsSort, pressed: ClassicsSortKey): ClassicsSort {
  if (current.key === pressed) return { key: pressed, direction: current.direction === 'desc' ? 'asc' : 'desc' };
  return { key: pressed, direction: 'desc' };
}

export function ratingValue(record: { imdbRating?: number | string | null } | null | undefined): number | null {
  const value = Number(record?.imdbRating);
  return Number.isFinite(value) && value > 0 ? value : null;
}

/**
 * Comparator for any card type. Rating sort: highest first, and equal ratings fall back to the newest year.
 * Titles without a rating always go last, whichever direction is chosen.
 */
export function classicsComparator<T>(
  sort: ClassicsSort,
  dateOf: (item: T) => number,
  ratingOf: (item: T) => number | null,
  titleOf: (item: T) => string,
): (a: T, b: T) => number {
  const byTitle = (a: T, b: T) => titleOf(a).localeCompare(titleOf(b), undefined, { numeric: true });
  const newestFirst = (a: T, b: T) => {
    const dateA = dateOf(a);
    const dateB = dateOf(b);
    if (dateA !== dateB) return dateB - dateA;
    return 0;
  };
  return (a, b) => {
    if (sort.key === 'rating') {
      const ratingA = ratingOf(a);
      const ratingB = ratingOf(b);
      if (ratingA === null && ratingB !== null) return 1;
      if (ratingA !== null && ratingB === null) return -1;
      if (ratingA !== null && ratingB !== null && ratingA !== ratingB) {
        return sort.direction === 'desc' ? ratingB - ratingA : ratingA - ratingB;
      }
      return newestFirst(a, b) || byTitle(a, b);
    }
    const dateA = dateOf(a);
    const dateB = dateOf(b);
    if (!dateA && dateB) return 1;
    if (dateA && !dateB) return -1;
    if (dateA !== dateB) return sort.direction === 'desc' ? dateB - dateA : dateA - dateB;
    const ratingA = ratingOf(a) ?? 0;
    const ratingB = ratingOf(b) ?? 0;
    return ratingB - ratingA || byTitle(a, b);
  };
}
