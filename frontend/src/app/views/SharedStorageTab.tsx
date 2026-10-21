import { Folder, FolderPlus, Share2, Users } from 'lucide-react';
import { formatBytes } from '../../utils/formatters.ts';
import type { PanelModel } from '../useAppModel.tsx';

export function SharedStorageTab({ vm }: { vm: PanelModel }) {
  const { activeTab, activeUser, folders, setActiveTab, setCurrentFolder, setIsCreateFolderOpen, setShareFolder } = vm;
  return (
    <>
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
    </>
  );
}
