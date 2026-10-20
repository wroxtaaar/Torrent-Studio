# Splitting the big frontend files

`frontend/src/components/TorrentSearchPanel.tsx` (5.6k lines) and `frontend/src/App.tsx`
(3.7k lines, one 3.6k-line component) are the two files to break up. Same rules as the
backend split ([main-split-plan.md](main-split-plan.md)): behavior must not change, every step is
small, ends green on CI and is pushed to `main`, and progress is ticked here so a later session
can pick up at the first open box.

**To continue:** open the first unchecked step, follow *How to do a step*, tick the box in the same commit.

## Progress

- [x] **F1 – Tooling + `TorrentSearchPanel` top-level helpers** → `components/torrent-search/` (`grouping`, `ottProviders`, `persistentCaches`, `formatting`, `nexstream`, `posterCache`, `cataloguePosters`). 5,590 → 4,646 lines; the component itself is still ~4,580 lines.
- [x] **F2 – Other large files with plain top-level code**: `api/client.ts` (1.5k) is now `api/types.ts` (response types), `api/http.ts` (`API_BASE`, `apiFetch`, CSRF token with getter/setter), and four method groups `api/search.ts`, `api/torrents.ts`, `api/seedr.ts`, `api/compat.ts`; `client.ts` is a 15-line facade (`api = { ...groups }`, re-exports `API_BASE` and all types), so no importer changed. `MovieCards.tsx`: staged poster upgrade code → `movie-cards/posterUpgrade.ts` (the two public helpers are re-exported). `MediaPlayerModal.tsx` (1.5k) and `AddMagnetModal.tsx` (0.9k) turned out to be a single component each with nothing top-level to move: see F8.
- [x] **F3 – `TorrentSearchPanel` inner helpers**: pure helpers and type aliases declared inside the component body (they use no props/state) → `torrent-search/posterUrls.ts`, `helpers.ts`, `types.ts`. `extract-top.cjs` got an inner mode (`... A-B,... ComponentName`) and `inner-candidates.cjs` lists what qualifies. Component: ~4,470 lines.
- [x] **F4a – `TorrentSearchPanel` state hooks**: every plain `useState`/`useRef` declaration (no props, no dependencies) now lives in a state hook under `torrent-search/state/`: `useNexStreamState`, `useSearchMetadataState`, `useMoviePreviewState`, `useCatalogueNavigationState`, `useWebSeriesState`, `useSearchInputState`, `usePosterState`, `usePrepareState`. The component destructures what it uses (`const { ... } = useX();`) so the rest of the code is unchanged. Props types → `torrent-search/props.ts`, cache constants → `constants.ts`. New tools: `state-graph.cjs` (per statement: what it declares, which earlier statements it depends on) and `extract-hook.cjs`. Component ~4,000 lines.
- [ ] **F4b (in progress; done so far: poster workers → `state/usePosterWorkers.ts`) – `TorrentSearchPanel` logic hooks**: the ~50 handlers/effects (`runSearch` 520 lines, `searchMovieTorrents` 290, poster background workers, NexStream episode flow, IMDb/metadata prefetch effects, ...) become hooks that take the state hooks' outputs as typed inputs (`ReturnType<typeof useX>`) and return their handlers. Do them in dependency order (see `state-graph.cjs`): poster workers → NexStream → prepare/preview → catalogue loading → search runner → prefetch effects. Effects keep their relative order (it is behavior).
- [ ] **F5 – `TorrentSearchPanel` JSX**: the 1,370-line `return` becomes sub-components (search bar, results, movie catalogue, NexStream player, preview modal) taking the hook outputs.
- [ ] **F6 – `App.tsx` hooks**: same as F4 for the single `App` component (Seedr library loading, add/prepare flow, playback, delete, notifications).
- [ ] **F7 – `App.tsx` JSX**: the 984-line `return` becomes view components (header/nav, library, search tab, modals).
- [ ] **F8 – `MediaPlayerModal` and `AddMagnetModal`**: same hook / sub-component treatment as F4–F5 (player controls, HLS/subtitle/audio tracks; magnet inspect, file selection).
- [ ] **F9 – Final cleanup**: no file over ~800 lines (target), README note, remove tooling that is no longer needed.

> F4–F7 are exploratory: re-read the state graph at the start of each step and
> adjust the list (and this document) before moving code.

## Rule: one initial card, one prepare card

Every section must render the shared cards, so a change to a card applies everywhere:

* **Initial card** = `MovieCompactCard` (`components/MovieCards.tsx`). Movie sections use it directly;
  TV / web-series sections (4 catalogue grids + NexStream TV search) use it through `torrent-search/TvShowCard.tsx`.
* **Prepare card** = `MoviePrepareCard` (movie catalogue sections and normal search results).
* No section may hand-write card markup: CI fails on `<article` outside `MovieCatalogueCard.tsx`.
* When splitting JSX (F5/F7) the new section components must keep using these; never copy a card.

## How to do a step

The authoring sandbox has no npm access, so the checks that CI does with `tsc` and `vite build`
are approximated offline with the TypeScript compiler API (global install); **CI is the final judge**.

```bash
cd frontend
node ../scripts/frontend-split/frontcheck.cjs                       # baseline: "ok: N files, ..."
node ../scripts/frontend-split/outline.cjs src/components/X.tsx     # top-level statements with line ranges
node ../scripts/frontend-split/body.cjs    src/components/X.tsx X   # statements inside a component body
node ../scripts/frontend-split/extract-top.cjs plan  src/components/X.tsx src/components/x/new.ts 100-220,300-340
node ../scripts/frontend-split/extract-top.cjs apply src/components/X.tsx src/components/x/new.ts 100-220,300-340
node ../scripts/frontend-split/inner-candidates.cjs src/components/X.tsx X      # statements inside component X that need no component state
node ../scripts/frontend-split/extract-top.cjs apply src/components/X.tsx src/components/x/new.ts 622-629,649-653 X   # inner mode (note the component name)
node ../scripts/frontend-split/state-graph.cjs src/components/X.tsx X           # per body statement: declarations and dependencies
node ../scripts/frontend-split/extract-hook.cjs apply src/components/X.tsx X useThing src/components/x/state/useThing.ts 60-75,120-130
node ../scripts/frontend-split/frontcheck.cjs                       # must still be ok
```

* `extract-top` moves whole top-level statements, adds `export`, creates the new module's imports
  (rewriting relative paths), imports the moved names back into the source, and drops imports the
  source no longer needs. It refuses (and says why) when moved code uses a top-level name that
  would stay behind (that would be a circular import) - move that name in the same step.
* **Line numbers are those of the current file.** Applying a move shifts everything below it; do
  several moves bottom-up, or re-run `outline.cjs` between moves.
* Modules that contain JSX must end in `.tsx`.
* Commit, push to `main`, wait for CI (frontend job runs `npm run lint` = `tsc --noEmit`, then the build).

## Notes

* `tsconfig.json` is not strict and has no `noUnusedLocals`, so leftover unused imports do not fail CI;
  the tool still removes the ones it makes unused.
* Import style in this repo: explicit `.ts` / `.tsx` extensions.
