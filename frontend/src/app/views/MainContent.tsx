import { Cloud, Folder, FolderPlus, Share2, Search, AlertTriangle, RefreshCw, Users, ChevronRight, CheckCircle2, Loader2 } from 'lucide-react';
import { formatBytes, formatQuotaBytes } from '../../utils/formatters.ts';
import { FileCard } from '../../components/FileCard.tsx';
import { TorrentSearchPanel } from '../../components/TorrentSearchPanel.tsx';
import type { PanelModel } from '../useAppModel.tsx';

export function MainContent({ vm }: { vm: PanelModel }) {
  const { activeTab, activeUser, backgroundMetadataJob, currentFolder, fileSearch, fileTypeFilter, folders, handleAddMagnet, handleCancelSeedrDownload, handleDeleteSeedrFile, handleSearchPrepare, handleStreamSeedrFile, isCancellingSeedr, loadSeedrLibrary, openMetadataSelector, seedrAddBlockedNotice, seedrAllPrefetchedFiles, seedrConfigured, seedrDeleteNotice, seedrDeletedFolderIds, seedrDownloadActive, seedrError, seedrInsufficientSpacePrompt, seedrLibraryFolders, seedrLibraryRoot, seedrLoading, seedrNotice, seedrPrefetchLoading, seedrQuota, seedrQuotaError, seedrStreamLoadingId, setActiveMediaFile, setActiveTab, setBackgroundMetadataJob, setCurrentFolder, setFileSearch, setFileTypeFilter, setIsCreateFolderOpen, setIsPlayerMinimized, setMoveFile, setRenameItem, setSeedrError, setSeedrInsufficientSpacePrompt, setShareFolder, visibleFiles, visibleFolders } = vm;
  return (
    <>
      <main className="flex-1 max-w-7xl w-full mx-auto p-2.5 sm:p-6 pb-20 md:pb-12">
        {seedrAddBlockedNotice && (
          <div className="mb-2.5 sm:mb-4 p-2.5 sm:p-3.5 rounded-xl sm:rounded-2xl bg-amber-500/10 border border-amber-500/30 text-amber-200 text-xs flex items-start gap-2.5 shadow-lg">
            <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
            <div className="min-w-0">
              <div className="font-bold text-amber-300">Cannot add another Seedr download</div>
              <div className="mt-0.5 text-amber-200/80">{seedrAddBlockedNotice}</div>
            </div>
          </div>
        )}

        {/* TAB 0: TORRENT SEARCH
            Keep this component mounted when switching tabs so an in-flight
            search continues in the background and its results remain available
            when the user returns to Search. */}
        <div className={activeTab === 'search' ? 'block' : 'hidden'}>
          <TorrentSearchPanel
            onPrepare={handleSearchPrepare}
            onCancelPrepare={handleCancelSeedrDownload}
            onOpenProgress={() => {
              setActiveTab('files');
            }}
            seedrFiles={seedrAllPrefetchedFiles}
            seedrDeletedFolderIds={seedrDeletedFolderIds}
            onPlaySeedrFile={handleStreamSeedrFile}
          />

          {seedrInsufficientSpacePrompt && (
            <div className="fixed inset-x-3 top-20 z-[100] flex justify-center pointer-events-none">
              <div className="w-full max-w-md rounded-2xl border border-rose-400/40 bg-slate-950/95 backdrop-blur-xl shadow-[0_0_30px_rgba(244,63,94,0.22)] p-4 pointer-events-auto">
                <div className="flex items-start gap-3">
                  <div className="shrink-0 rounded-xl bg-rose-500/10 border border-rose-500/20 p-2">
                    <AlertTriangle className="w-5 h-5 text-rose-400" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="font-bold text-rose-300 text-sm">Seedr storage is full</div>
                    <div className="mt-1 text-xs leading-5 text-slate-300">
                      This torrent needs <span className="font-semibold text-slate-100">{formatBytes(seedrInsufficientSpacePrompt.requiredBytes)}</span>,
                      but only <span className="font-semibold text-rose-300">{formatBytes(seedrInsufficientSpacePrompt.remainingBytes)}</span> is available.
                    </div>
                    <div className="mt-3 flex gap-2">
                      <button
                        type="button"
                        onClick={() => {
                          const prompt = seedrInsufficientSpacePrompt;
                          setSeedrInsufficientSpacePrompt(null);
                          void handleAddMagnet(
                            prompt.magnet,
                            prompt.category,
                            prompt.selectedFiles,
                            prompt.manifest,
                            prompt.existingHash,
                            'qbittorrent'
                          );
                        }}
                        className="flex-1 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-slate-950 px-3 py-2 text-xs font-bold transition"
                      >
                        Use qBittorrent
                      </button>
                      <button
                        type="button"
                        onClick={() => setSeedrInsufficientSpacePrompt(null)}
                        className="rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 px-3 py-2 text-xs font-semibold transition"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* TAB 2: MY CLOUD FILES */}
        {activeTab === 'files' && (
          <div className="space-y-2.5 sm:space-y-4">
            {/* Persistent Seedr Library */}
            <div className="p-2.5 sm:p-4 rounded-xl sm:rounded-2xl bg-emerald-500/5 border border-emerald-500/20">
              {seedrDeleteNotice && (
                <div className="mb-3 flex items-center gap-2 rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3 py-2 text-xs text-emerald-300">
                  <CheckCircle2 className="w-4 h-4" />
                  <span>{seedrDeleteNotice}</span>
                </div>
              )}
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div className="min-w-0">
                  <h2 className="text-base font-bold text-slate-100 flex items-center gap-2">
                    <Cloud className="w-5 h-5 text-emerald-400" />
                    <span>Seedr Library</span>
                    {seedrConfigured && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-300 border border-emerald-500/20">
                        {seedrLibraryRoot?.filesCount || 0} files
                      </span>
                    )}
                  </h2>
                  <p className="hidden sm:block text-xs text-slate-400 mt-0.5">
                    Files already downloaded to your Seedr account stay visible here, even after refreshing Torrent Studio.
                  </p>
                  {seedrConfigured && (
                    seedrQuota ? (
                      <>                      <div className="grid mt-3 grid-cols-3 gap-2 max-w-xl">
                        <div className="rounded-lg bg-slate-900/80 border border-slate-800 px-3 py-2">
                          <div className="text-[10px] uppercase tracking-wide text-slate-500">Consumed</div>
                          <div className="text-sm font-bold text-slate-100 mt-0.5">{formatBytes(seedrQuota.usedSpace)}</div>
                        </div>
                        <div
                          className={`rounded-lg px-3 py-2 border transition-all duration-300 ${
                            seedrQuota.remainingSpace > 0 && seedrQuota.remainingSpace < 500 * 1024 * 1024
                              ? 'border-rose-400/70 bg-rose-400/10 ring-1 ring-rose-400/30 shadow-[0_0_18px_rgba(244,63,94,0.24)]'
                              : seedrQuota.maxSpace > 0 && seedrQuota.remainingSpace / seedrQuota.maxSpace <= 0.3
                                ? 'border-amber-400/60 bg-amber-400/10 ring-1 ring-amber-400/25 shadow-[0_0_18px_rgba(251,191,36,0.18)]'
                                : 'bg-slate-900/80 border-slate-800'
                          }`}
                        >
                          <div className={`text-[10px] uppercase tracking-wide ${
                            seedrQuota.remainingSpace > 0 && seedrQuota.remainingSpace < 500 * 1024 * 1024
                              ? 'text-rose-300'
                              : seedrQuota.maxSpace > 0 && seedrQuota.remainingSpace / seedrQuota.maxSpace <= 0.3
                                ? 'text-amber-300'
                                : 'text-slate-500'
                          }`}>Remaining</div>
                          <div className={`text-sm font-bold mt-0.5 ${
                            seedrQuota.remainingSpace <= 0
                              ? 'text-rose-300'
                              : seedrQuota.remainingSpace < 500 * 1024 * 1024
                                ? 'text-rose-300'
                                : seedrQuota.maxSpace > 0 && seedrQuota.remainingSpace / seedrQuota.maxSpace <= 0.3
                                  ? 'text-amber-300'
                                  : 'text-emerald-300'
                          }`}>
                            {formatQuotaBytes(seedrQuota.remainingSpace)}
                          </div>
                        </div>
                        <div className="rounded-lg bg-slate-900/80 border border-slate-800 px-3 py-2">
                          <div className="text-[10px] uppercase tracking-wide text-slate-500">Total</div>
                          <div className="text-sm font-bold text-slate-100 mt-0.5">{formatBytes(seedrQuota.maxSpace)}</div>
                        </div>
                      </div>


                    </>
                    ) : null
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => { void loadSeedrLibrary(true); }}
                  disabled={seedrLoading}
                  className="shrink-0 px-2 sm:px-3 py-1.5 rounded-lg sm:rounded-xl bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-slate-200 text-xs font-semibold flex items-center gap-1.5 transition"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${seedrLoading ? 'animate-spin' : ''}`} />
                  <span>{seedrLoading ? 'Refreshing...' : 'Refresh'}</span>
                </button>
              </div>

              {seedrConfigured && seedrQuota && seedrQuota.remainingSpace <= 0 && (
                <div className="mt-3 rounded-xl bg-rose-500/10 border border-rose-500/20 px-3 py-2.5 text-xs text-rose-200">
                  <strong>Seedr is full.</strong> New torrents that fit the Seedr size limit will be offered to qBittorrent instead, or you can free space in Seedr and try again.
                </div>
              )}

              {seedrError && (
                <div className="mt-3 rounded-xl bg-rose-500/10 border border-rose-500/20 px-3 py-2 text-xs text-rose-300">
                  {seedrError}
                </div>
              )}

              {seedrQuotaError && !seedrError && (
                <div className="mt-3 rounded-xl bg-amber-500/10 border border-amber-500/20 px-3 py-2 text-xs text-amber-200">
                  {seedrQuotaError}
                </div>
              )}

              {!seedrLoading && !seedrError && !seedrConfigured && (
                <div className="mt-3 rounded-xl bg-slate-900/70 border border-slate-800 px-3 py-3 text-xs text-slate-400">
                  Seedr is not configured on the server.
                </div>
              )}

              {!seedrLoading && !seedrError && seedrConfigured && (seedrLibraryRoot?.filesCount || 0) === 0 && seedrLibraryFolders.length === 0 && !(seedrNotice?.taskId != null && seedrNotice.status !== 'completed') && (
                <div className="mt-3 rounded-xl bg-slate-900/70 border border-slate-800 px-3 py-3 text-xs text-slate-400">
                  No completed files are currently visible in your Seedr library.                </div>
              )}

              {seedrConfigured && seedrPrefetchLoading && seedrAllPrefetchedFiles.length === 0 && (
                <div className="mt-3 rounded-xl border border-cyan-500/20 bg-cyan-500/5 px-3 py-3 text-xs text-slate-400">
                  <div className="flex items-center gap-2">
                    <Loader2 className="h-4 w-4 animate-spin text-cyan-400" />
                    <span>Loading your Seedr files…</span>
                  </div>
                </div>
              )}


            {/* Header & Breadcrumb & Search */}
            <div className="flex flex-col gap-2 p-2.5 sm:p-4 rounded-xl sm:rounded-2xl bg-slate-900 border border-slate-800">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                {/* Folder Breadcrumb */}
                <div className="flex items-center gap-2 overflow-x-auto text-xs font-semibold">
                  <button
                    onClick={() => setCurrentFolder('/')}
                    className={`px-2.5 py-1.5 rounded-lg transition ${
                      currentFolder === '/'
                        ? 'bg-cyan-500/20 text-cyan-400'
                        : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    Root
                  </button>

                </div>


              </div>

              {/* Search & Category Filter */}
              <div className="flex flex-col sm:flex-row items-center gap-2.5 pt-2 border-t border-slate-800/80">
                <div className="relative flex-1 w-full">
                  <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
                  <input
                    type="text"
                    placeholder="Search files by name..."
                    value={fileSearch}
                    onChange={(e) => setFileSearch(e.target.value)}
                    className="w-full pl-9 pr-3 py-2 sm:py-1.5 rounded-lg sm:rounded-xl bg-slate-950 border border-slate-800 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-cyan-500"
                  />
                </div>

                <div className="flex items-center gap-1 overflow-x-auto w-full sm:w-auto text-xs">
                  {['all', 'video', 'audio', 'document', 'archive'].map((t) => (
                    <button
                      key={t}
                      onClick={() => setFileTypeFilter(t)}
                      className={`px-2.5 py-1 rounded-lg capitalize font-medium transition ${
                        fileTypeFilter === t
                          ? 'bg-cyan-500 text-slate-950 font-bold'
                          : 'bg-slate-850 text-slate-400 hover:text-slate-200'
                      }`}
                    >
                      {t}
                    </button>
                  ))}
                </div>              </div>
            </div>

            {/* Folders and Files */}
                {visibleFolders.length > 0 ? (
                  <div className="grid grid-cols-1 gap-2.5">
                    {visibleFolders
                      .map((folder) => (
                        <button
                          key={folder.id}                          type="button"
                          onClick={() => setCurrentFolder(folder.path)}
                          className="w-full p-3.5 rounded-2xl bg-slate-900 border border-slate-800 hover:border-cyan-500/40 hover:bg-slate-900/80 transition shadow-sm flex items-center gap-3 text-left group"
                        >
                          <div className="p-2.5 rounded-xl bg-cyan-500/10 border border-cyan-500/20 shrink-0">
                            <Folder className="w-5 h-5 text-cyan-400" />
                          </div>
                          <div className="truncate flex-1">
                            <h4 className="text-sm font-semibold text-slate-200 truncate group-hover:text-cyan-400 transition">
                              {folder.name}
                            </h4>
                            <p className="text-[11px] text-slate-500 mt-0.5">
                              {folder.filesCount || 0} files • {formatBytes(folder.totalSize || 0)}
                            </p>
                          </div>
                          <ChevronRight className="w-4 h-4 text-slate-600 group-hover:text-cyan-400 shrink-0" />
                        </button>
                      ))}
                  </div>
                ) : null}

                {visibleFiles.length > 0 && (
                  <div className="grid grid-cols-1 gap-2.5">
                    {visibleFiles.map((file) => (
                      <FileCard
                        key={file.id}
                        file={file}
                        onPlay={(f) => {
                          // Root "My Cloud Files" rows are Seedr files too, but
                          // they must use the same resolver as the working folder
                          // view so Vercel + Render always targets the backend.
                          if (
                            f.ownerId === 'seedr' &&
                            (f.type === 'video' || f.type === 'audio')
                          ) {
                            void handleStreamSeedrFile({
                              id: f.id,
                              streamId: f.streamId || f.id,
                              name: f.name,
                              size: f.size,
                              folderId: '',
                              folderPath: f.folder || '/'
                            });
                            return;
                          }

                          setActiveMediaFile(f);
                          setIsPlayerMinimized(false);
                        }}
                        streamLoading={file.ownerId === 'seedr' && seedrStreamLoadingId === file.id}
                        onRename={(f) => setRenameItem({ id: f.id, name: f.name, isFolder: false })}
                        onMove={(f) => setMoveFile(f)}
                        onSeedrDelete={file.ownerId === 'seedr'
                          ? (f) => {
                              const seedrFile = seedrAllPrefetchedFiles.find(item => item.id === f.id);
                              if (!seedrFile) {
                                setSeedrError('Seedr file is no longer available. Refresh the library and try again.');
                                return;
                              }
                              return handleDeleteSeedrFile(seedrFile);
                            }
                          : undefined}
                        canEdit={activeUser?.role !== 'viewer'}
                        canDelete={file.ownerId === 'seedr' ? true : activeUser?.role === 'admin'}
                      />
                    ))}
                  </div>
                )}

                {seedrPrefetchLoading && currentFolder === '/' && seedrAllPrefetchedFiles.length === 0 ? (
                  <div className="py-10 text-center rounded-2xl bg-slate-900 border border-slate-800 p-8">
                    <RefreshCw className="w-8 h-8 text-emerald-400 mx-auto mb-3 animate-spin" />
                    <h3 className="text-sm font-bold text-slate-300">Loading Seedr files…</h3>
                    <p className="text-xs text-slate-500 mt-1">Folder metadata is ready. Loading file details in the background.</p>
                  </div>
                ) : visibleFolders.length === 0 && visibleFiles.length === 0 && (
                  <div className="py-16 text-center rounded-2xl bg-slate-900 border border-slate-800 p-8">
                    <Folder className="w-12 h-12 text-slate-700 mx-auto mb-3" />
                    <h3 className="text-sm font-bold text-slate-300">No files found in this folder</h3>
                    <p className="text-xs text-slate-500 mt-1">
                      Completed torrent downloads and uploaded media appear here instantly.
                    </p>
                  </div>
                )}

                {backgroundMetadataJob && (
                  <div className={`mt-3 rounded-xl border px-3 py-3 ${backgroundMetadataJob.error ? 'border-rose-500/30 bg-rose-500/10' : backgroundMetadataJob.ready ? 'border-emerald-500/30 bg-emerald-500/10' : 'border-cyan-500/30 bg-cyan-500/10'}`}>
                    <div className="flex items-center gap-3">
                      <Loader2 className={`w-5 h-5 shrink-0 ${backgroundMetadataJob.ready ? 'text-emerald-400' : backgroundMetadataJob.error ? 'text-rose-400' : 'text-cyan-400 animate-spin'}`} />
                      <div className="min-w-0 flex-1">
                        <div className="text-xs font-bold text-slate-100">{backgroundMetadataJob.title}</div>
                        <div className="text-[11px] text-slate-400 mt-0.5">{backgroundMetadataJob.message}</div>
                      </div>
                      <button
                        type="button"
                        onClick={() => {
                          const source = backgroundMetadataJob.hash
                            ? 'magnet:?xt=urn:btih:' + backgroundMetadataJob.hash
                            : '';
                          openMetadataSelector(source);
                          setActiveTab('files');
                        }}
                        className="px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-[11px] font-semibold"
                      >
                        Open
                      </button>
                      <button
                        type="button"
                        onClick={() => setBackgroundMetadataJob(null)}
                        className="p-1 rounded-lg text-slate-500 hover:text-slate-200"
                        aria-label="Dismiss metadata status"
                      >
                        ×
                      </button>
                    </div>
                  </div>
                )}

                {seedrDownloadActive && seedrNotice && (
                  <div className="mt-3 rounded-xl border border-emerald-500/25 bg-emerald-500/5 px-3.5 py-3">
                    <div className="flex items-center gap-3">
                      <Loader2 className="h-5 w-5 shrink-0 animate-spin text-emerald-400" />
                      <div className="min-w-0 flex-1">
                        <div className="text-xs font-bold text-slate-100 truncate">Loading {seedrNotice.name || 'torrent'} in Seedr</div>
                        <div className="mt-0.5 text-[11px] text-slate-400">{Number(seedrNotice.progress || 0).toFixed(1)}% complete</div>
                        <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
                          <div className="h-full rounded-full bg-emerald-400 transition-all duration-500" style={{ width: Math.max(0, Math.min(100, Number(seedrNotice.progress) || 0)) + '%' }} />
                        </div>
                      </div>
                      <button type="button" onClick={() => void handleCancelSeedrDownload()} disabled={isCancellingSeedr} className="shrink-0 rounded-lg border border-rose-500/25 bg-rose-500/10 px-2.5 py-1.5 text-[10px] font-bold text-rose-300 hover:bg-rose-500/20 disabled:opacity-50">
                        {isCancellingSeedr ? 'Cancelling…' : 'Cancel'}
                      </button>
                    </div>
                  </div>
                )}

              </div>
            </div>
        )}

        {/* TAB 3: SHARED STORAGE & MULTI-USER */}
        {activeTab === 'shared' && (
          <div className="space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-4 rounded-2xl bg-slate-900 border border-slate-800">
              <div>
                <h2 className="text-base font-bold text-slate-100 flex items-center gap-2">
                  <Users className="w-5 h-5 text-cyan-400" />
                  <span>Shared Team Folders & Access Controls</span>
                </h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  Multi-user folder permissions with customizable Viewer, Editor, and Admin roles.
                </p>
              </div>

              <button
                onClick={() => setIsCreateFolderOpen(true)}
                className="px-3.5 py-2 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-bold text-xs flex items-center gap-1.5 transition"
              >
                <FolderPlus className="w-4 h-4" />
                <span>New Shared Folder</span>
              </button>
            </div>

            {/* Folders List */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {folders.filter(f => f.path !== '/').map((folder) => {
                const isOwner = folder.ownerId === activeUser?.id;
                const userPerm = isOwner ? 'admin' : folder.permissions[activeUser?.id || ''] || 'viewer';

                  return (
                  <div
                    key={folder.id}
                    className="p-4 rounded-2xl bg-slate-900 border border-slate-800 hover:border-slate-700 transition flex flex-col justify-between gap-3"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2.5 overflow-hidden">
                        <div className="p-2.5 rounded-xl bg-cyan-500/10 text-cyan-400 shrink-0">
                          <Folder className="w-[18px] h-[18px]" />
                        </div>
                        <div className="truncate">
                          <h4 className="text-sm font-semibold text-slate-100 truncate">{folder.name}</h4>
                          <p className="text-[11px] text-slate-400 mt-0.5">
                            Created by {folder.ownerName}
                          </p>
                        </div>
                      </div>

                      <span
                        className={`text-[10px] font-bold px-2 py-0.5 rounded-full uppercase ${
                          folder.isShared                            ? 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/20'
                            : 'bg-slate-800 text-slate-400'
                        }`}
                      >
                        {folder.isShared ? 'Shared' : 'Private'}
                      </span>
                    </div>

                    <div className="flex items-center justify-between text-xs text-slate-400 pt-2 border-t border-slate-800/60">
                      <span>{folder.filesCount || 0} files ({formatBytes(folder.totalSize || 0)})</span>
                      <span className="text-cyan-400 font-medium capitalize">Role: {userPerm}</span>                    </div>

                    <div className="flex items-center gap-2 pt-1">
                      <button
                        onClick={() => {
                          setCurrentFolder(folder.path);
                          setActiveTab('files');
                        }}
                        className="flex-1 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold transition"
                      >
                        Open Folder
                      </button>

                      <button
                        onClick={() => setShareFolder(folder)}
                        className="p-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-cyan-400 transition"
                        title="Manage Permissions"
                      >
                        <Share2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
        {/* Activity Log and Auto-Cleanup/Disk tabs are intentionally hidden. */}

      </main>
    </>
  );
}
