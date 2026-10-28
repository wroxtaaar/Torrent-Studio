export type NexStreamTitle = { id: number; title: string; date: string; overview: string; poster: string | null; type: 'movie' | 'tv'; direct?: boolean; anime?: boolean };

export type FranchiseTmdbKey = 'marvel' | 'dc-live-action' | 'dc-animated';

export type CachedFranchiseKey = 'marvel' | 'dc-live-action';

export type MainCatalogueMenu = 'dc' | 'bollywood' | 'hollywood';

export type ActiveTopSection = 'marvel' | 'dc' | 'hollywood' | 'bollywood' | 'classics' | null;

export type RegionalContentTab = 'movies' | 'web-series' | null;

export type ClassicsContentTab = 'movies' | 'web-series' | 'anime';

export type RegionalCatalogueGroup = 'bollywood' | 'hollywood';

export type RegionalCatalogueMode = 'popular' | 'trending' | 'latest';

export type RegionalTvGroup = 'indian' | 'hollywood';

export type RegionalTvMode = 'popular' | 'trending' | 'latest';

export type MarvelFilmFilter = 'all' | 'mcu' | 'x-men' | 'sony';
