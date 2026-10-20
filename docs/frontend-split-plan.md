# Splitting the big frontend files

`frontend/src/components/TorrentSearchPanel.tsx` (5.6k lines) and `frontend/src/App.tsx`
(3.7k lines, one 3.6k-line component) are the two files to break up. Same rules as the
backend split ([main-split-plan.md](main-split-plan.md)): behavior must not change, every step is
small, ends green on CI and is pushed to `main`, and progress is ticked here so a later session
can pick up at the first open box.

**To continue:** open the first unchecked step, follow *How to do a step*, tick the box in the same commit.

## Progress

- [x] **F1 – Tooling + `TorrentSearchPanel` top-level helpers** → `components/torrent-search/` (`grouping`, `ottProviders`, `persistentCaches`, `formatting`, `nexstream`, `posterCache`, `cataloguePosters`). 5,590 → 4,646 lines; the component itself is still ~4,580 lines.
- [ ] **F2 – Other large files with plain top-level code**: `api/client.ts` (1.5k: split types from endpoint groups, keep `api` object re-exported), `MediaPlayerModal.tsx` (1.5k), `AddMagnetModal.tsx` (0.9k), `MovieCards.tsx` (0.7k): move helpers/types out with `extract-top.cjs`.
- [ ] **F3 – `TorrentSearchPanel` inner helpers**: the 12 type aliases and the pure functions declared *inside* the component body (e.g. `loadCachedFranchisePage` if it only needs its arguments) become module-level code. Needs `extract-inner` (extend the tool: only statements whose free names are not component-scope variables).
- [ ] **F4 – `TorrentSearchPanel` hooks**: split the ~240 body statements into custom hooks by concern (NexStream, poster workers, IMDb/metadata prefetch, franchise/catalogue browsing, search runner). Types come from `ReturnType<typeof useX>` so no props have to be typed by hand; hooks are called in the original order so React's hook order is unchanged.
- [ ] **F5 – `TorrentSearchPanel` JSX**: the 1,370-line `return` becomes sub-components (search bar, results, movie catalogue, NexStream player, preview modal) taking the hook outputs.
- [ ] **F6 – `App.tsx` hooks**: same as F4 for the single `App` component (Seedr library loading, add/prepare flow, playback, delete, notifications).
- [ ] **F7 – `App.tsx` JSX**: the 984-line `return` becomes view components (header/nav, library, search tab, modals).
- [ ] **F8 – Final cleanup**: no file over ~800 lines (target), README note, remove tooling that is no longer needed.

> F4–F7 are exploratory: re-read the state graph at the start of each step and
> adjust the list (and this document) before moving code.

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
