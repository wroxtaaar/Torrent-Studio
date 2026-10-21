import { MessageSquare } from 'lucide-react';
import { api } from '../../api/client.ts';
import { dispatchBrowserNotification } from '../../utils/notifications.ts';
import { AddMagnetModal } from '../../components/AddMagnetModal.tsx';
import { FilePrioModal } from '../../components/FilePrioModal.tsx';
import { StorageCleanupModal } from '../../components/StorageCleanupModal.tsx';
import { FolderShareModal } from '../../components/FolderShareModal.tsx';
import { NotificationCenter } from '../../components/NotificationCenter.tsx';
import { CreateFolderModal } from '../../components/CreateFolderModal.tsx';
import { MoveFileModal } from '../../components/MoveFileModal.tsx';
import { RenameModal } from '../../components/RenameModal.tsx';
import { ConfirmDeleteModal } from '../../components/ConfirmDeleteModal.tsx';
import type { PanelModel } from '../useAppModel.tsx';

export function AppModals({ vm }: { vm: PanelModel }) {
  const { cleanupSettings, currentFolder, deleteTarget, feedbackError, feedbackMessage, feedbackName, feedbackOpen, feedbackRating, feedbackSubmitting, feedbackSuccess, feedbackType, folders, handleAddMagnet, handleConfirmDelete, handleCreateFolder, handleFolderShareSave, handleMoveFile, handleRename, handleRunCleanup, handleUpdateFilePriority, initialDescriptorUrl, initialMagnet, initialSourceUrl, isAddMagnetOpen, isCleanupOpen, isCreateFolderOpen, isNotificationsOpen, moveFile, notifications, openAddMagnet, prioTorrent, renameItem, setActiveTab, setBackgroundMetadataJob, setCleanupSettings, setDeleteTarget, setFeedbackMessage, setFeedbackName, setFeedbackOpen, setFeedbackRating, setFeedbackType, setInitialDescriptorUrl, setInitialMagnet, setInitialSourceUrl, setIsAddMagnetOpen, setIsCleanupOpen, setIsCreateFolderOpen, setIsNotificationsOpen, setMoveFile, setNotifications, setPrioTorrent, setRenameItem, setShareFolder, shareFolder, storageStats, submitFeedback, users } = vm;
  return (
    <>
      <AddMagnetModal
        isOpen={isAddMagnetOpen}
        onClose={() => {
          setIsAddMagnetOpen(false);
          setInitialMagnet('');
          setInitialSourceUrl('');
          setInitialDescriptorUrl('');
        }}
        onOpen={() => {
          openAddMagnet(initialMagnet);
        }}
        onAdd={handleAddMagnet}
        onBackgroundChange={(state) => {
          setBackgroundMetadataJob(state);
          if (state.active) {
            setActiveTab('files');
            setIsAddMagnetOpen(false);
          }
        }}
        defaultFolder={currentFolder === '/' ? 'Downloads' : currentFolder.replace('/', '')}
        initialMagnet={initialMagnet}
        initialSourceUrl={initialSourceUrl}
        initialDescriptorUrl={initialDescriptorUrl}
      />

      <FilePrioModal
        torrent={prioTorrent}
        onClose={() => setPrioTorrent(null)}
        onUpdatePriority={handleUpdateFilePriority}
      />

      <StorageCleanupModal
        isOpen={isCleanupOpen}
        onClose={() => setIsCleanupOpen(false)}
        stats={storageStats}
        settings={cleanupSettings}
        onUpdateSettings={async (settings) => {
          const updated = await api.updateCleanupSettings(settings);
          setCleanupSettings(updated);
        }}
        onRunCleanup={handleRunCleanup}
      />

      <FolderShareModal
        folder={shareFolder}
        users={users}
        onClose={() => setShareFolder(null)}
        onSave={handleFolderShareSave}
      />

      <NotificationCenter
        notifications={notifications}
        isOpen={isNotificationsOpen}
        onClose={() => setIsNotificationsOpen(false)}
        onMarkRead={async () => {
          await api.markNotificationsRead();
          setNotifications(prev => prev.map(n => ({ ...n, read: true })));
        }}
        onTestPush={async () => {
          await api.testNotification();
          dispatchBrowserNotification('Torrent Studio Push Notification Test', 'Push alert successfully triggered! Everything is running smoothly.');
          const notifs = await api.getNotifications();
          setNotifications(notifs);
        }}      />

      <CreateFolderModal
        isOpen={isCreateFolderOpen}
        onClose={() => setIsCreateFolderOpen(false)}
        onCreate={handleCreateFolder}
        currentPath={currentFolder}
      />

      <MoveFileModal
        file={moveFile}
        folders={folders}        onClose={() => setMoveFile(null)}
        onMove={handleMoveFile}
      />

      <RenameModal
        item={renameItem}
        onClose={() => setRenameItem(null)}
        onRename={handleRename}
      />

      {deleteTarget && (
        <ConfirmDeleteModal
          isOpen={Boolean(deleteTarget)}
          title={deleteTarget.type === 'file' ? 'Delete File' : 'Remove Torrent Task'}
          itemName={deleteTarget.name}
          itemDetails={deleteTarget.details}
          itemType={deleteTarget.type}
          onConfirm={handleConfirmDelete}
          onClose={() => setDeleteTarget(null)}
        />
      )}
      {feedbackOpen && (
        <div
          className="fixed inset-0 z-[110] flex items-center justify-center bg-slate-950/70 px-4 py-6 backdrop-blur-md"
          role="dialog"
          aria-modal="true"
          aria-labelledby="feedback-title"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setFeedbackOpen(false);
          }}
        >
          <div
            className="relative w-full max-w-md rounded-2xl border border-cyan-500/20 bg-slate-900 p-5 shadow-2xl sm:p-6"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <button
              type="button"
              aria-label="Close feedback"
              onClick={() => setFeedbackOpen(false)}
              className="absolute right-3 top-3 flex h-9 w-9 items-center justify-center rounded-full text-slate-400 transition hover:bg-slate-800 hover:text-white"
            >
              <span className="text-2xl leading-none">×</span>
            </button>

            <div className="flex items-start gap-3 pr-8">
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-cyan-500/10 text-cyan-400">
                <MessageSquare className="h-6 w-6" />
              </div>
              <div>
                <h2 id="feedback-title" className="text-lg font-bold text-slate-100">Feedback</h2>
                <p className="mt-1 text-sm leading-5 text-slate-400">
                  Tell us what you think, suggest an improvement, or report a problem.
                </p>
              </div>
            </div>

            <div className="mt-5 grid grid-cols-3 gap-2">
              {([
                ['review', 'Review'],
                ['suggestion', 'Suggestion'],
                ['bug', 'Problem'],
              ] as const).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setFeedbackType(value)}
                  className={feedbackType === value
                    ? 'rounded-xl bg-cyan-500 px-3 py-2.5 text-xs font-bold text-slate-950'
                    : 'rounded-xl border border-slate-700 bg-slate-800 px-3 py-2.5 text-xs font-semibold text-slate-300 hover:bg-slate-700'}
                >
                  {label}
                </button>
              ))}
            </div>

            {feedbackType === 'review' && (
              <div className="mt-4">
                <p className="text-xs font-semibold text-slate-300">Rating</p>
                <div className="mt-2 flex gap-1.5">
                  {[1, 2, 3, 4, 5].map(value => (
                    <button
                      key={value}
                      type="button"
                      onClick={() => setFeedbackRating(value)}
                      aria-label={`${value} star${value === 1 ? '' : 's'}`}
                      className={value <= feedbackRating ? 'text-amber-400 text-2xl leading-none' : 'text-slate-700 text-2xl leading-none'}
                    >
                      ★
                    </button>
                  ))}
                </div>
              </div>
            )}

            <textarea
              value={feedbackMessage}
              onChange={event => setFeedbackMessage(event.target.value)}
              placeholder={feedbackType === 'review' ? 'How is Torrent Studio for you?' : feedbackType === 'suggestion' ? 'What would you like us to add or improve?' : 'What went wrong?'}
              maxLength={3000}
              rows={5}
              className="mt-4 w-full resize-none rounded-xl border border-slate-700 bg-slate-950 px-3.5 py-3 text-sm text-slate-100 outline-none placeholder:text-slate-600 focus:border-cyan-500/50 focus:ring-2 focus:ring-cyan-500/10"
            />

            <input
              value={feedbackName}
              onChange={event => setFeedbackName(event.target.value)}
              maxLength={80}
              placeholder="Name (optional)"
              className="mt-3 w-full rounded-xl border border-slate-700 bg-slate-950 px-3.5 py-3 text-sm text-slate-100 outline-none placeholder:text-slate-600 focus:border-cyan-500/50 focus:ring-2 focus:ring-cyan-500/10"
            />

            {feedbackError && (
              <div className="mt-3 rounded-xl border border-rose-500/25 bg-rose-500/10 p-3 text-xs leading-5 text-rose-200">
                {feedbackError}
              </div>
            )}
            {feedbackSuccess && (
              <div className="mt-3 rounded-xl border border-emerald-500/25 bg-emerald-500/10 p-3 text-xs leading-5 text-emerald-200">
                {feedbackSuccess}
              </div>
            )}

            <button
              type="button"
              disabled={feedbackSubmitting || feedbackMessage.trim().length < 5}
              onClick={() => void submitFeedback()}
              className="mt-4 w-full rounded-xl bg-cyan-500 px-4 py-3 text-sm font-bold text-slate-950 transition hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {feedbackSubmitting ? 'Sending…' : 'Send Feedback'}
            </button>

            <p className="mt-3 text-center text-[11px] leading-4 text-slate-600">
              Your feedback is reviewed by the Torrent Studio team.
            </p>
          </div>
        </div>
      )}

    </>
  );
}
