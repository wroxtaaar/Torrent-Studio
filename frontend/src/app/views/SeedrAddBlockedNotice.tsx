import { AlertTriangle } from 'lucide-react';
import type { PanelModel } from '../useAppModel.tsx';

export function SeedrAddBlockedNotice({ vm }: { vm: PanelModel }) {
  const { seedrAddBlockedNotice } = vm;
  return (
    <>
        {seedrAddBlockedNotice && (
          <div className="mb-2.5 sm:mb-4 p-2.5 sm:p-3.5 rounded-xl sm:rounded-2xl bg-amber-500/10 border border-amber-500/30 text-amber-200 text-xs flex items-start gap-2.5 shadow-lg">
            <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
            <div className="min-w-0">
              <div className="font-bold text-amber-300">Cannot add another Seedr download</div>
              <div className="mt-0.5 text-amber-200/80">{seedrAddBlockedNotice}</div>
            </div>
          </div>
        )}
    </>
  );
}
