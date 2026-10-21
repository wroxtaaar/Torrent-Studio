import { Folder, Search, MessageSquare } from 'lucide-react';
import type { PanelModel } from '../useAppModel.tsx';

export function MobileNav({ vm }: { vm: PanelModel }) {
  const { activeTab, feedbackOpen, setActiveTab, setFeedbackError, setFeedbackOpen, setFeedbackSuccess } = vm;
  return (
    <>
      <nav className="md:hidden fixed bottom-0 left-0 right-0 z-50 bg-slate-950/95 backdrop-blur-xl border-t border-slate-800 px-1 pb-[calc(env(safe-area-inset-bottom)+2px)] pt-1">
        <div className="grid grid-cols-3 items-center">
          <button
            onClick={() => { setActiveTab('search'); }}
            className={`flex flex-col items-center justify-center gap-0.5 min-h-11 px-1 rounded-lg transition ${activeTab === 'search' ? 'text-cyan-400' : 'text-slate-400'}`}
          >
            <Search className="w-[18px] h-[18px]" />
            <span className="text-[9px] font-semibold">Search</span>
          </button>

          <button
            onClick={() => { setActiveTab('files'); }}
            className={`flex flex-col items-center justify-center gap-0.5 min-h-12 px-1 rounded-xl transition ${activeTab === 'files' ? 'text-cyan-400' : 'text-slate-400'}`}
          >
            <Folder className="w-5 h-5" />
            <span className="text-[9px] font-semibold">Files</span>
          </button>

          <button
            type="button"
            onClick={() => {
              setFeedbackOpen(true);
              setFeedbackSuccess('');
              setFeedbackError('');
            }}
            className={`flex flex-col items-center justify-center gap-0.5 min-h-12 px-1 rounded-xl transition ${feedbackOpen ? 'text-cyan-400' : 'text-slate-400'}`}
          >
            <MessageSquare className="w-5 h-5" />
            <span className="text-[9px] font-semibold">Feedback</span>
          </button>
        </div>
      </nav>
    </>
  );
}
