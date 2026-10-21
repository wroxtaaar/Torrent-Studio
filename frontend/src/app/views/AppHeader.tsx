import { Cloud, Folder, Bell, Search, Moon, CheckCircle2 } from 'lucide-react';
import type { PanelModel } from '../useAppModel.tsx';

export function AppHeader({ vm }: { vm: PanelModel }) {
  const { activeTab, files, seedrConnected, setActiveTab, setIsNotificationsOpen, setSeedrConnectError, setSeedrOnboardingOpen, setSeedrPat, setTheme, theme, unreadNotifsCount } = vm;
  return (
    <>
      <header className="sticky top-0 z-40 bg-slate-950/90 backdrop-blur-md border-b border-slate-800/80 px-2.5 sm:px-6 py-1.5 sm:py-3">
        <div className="max-w-7xl mx-auto flex items-center justify-between gap-2 sm:gap-3">
          {/* Logo & Brand */}
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-cyan-500 via-blue-600 to-indigo-600 flex items-center justify-center shadow-lg shadow-cyan-500/25">
              <Cloud className="w-4 h-4 sm:w-5 sm:h-5 text-slate-950 font-black fill-current" />
            </div>
            <div>
              <div className="flex items-center gap-1.5 sm:gap-2">
                <h1 className="text-sm sm:text-lg font-black tracking-tight text-white">Torrent Studio</h1>
</div>
              <p className="text-[10px] text-slate-400 hidden sm:block">
                Unlimited Cloud Seedbox & Media Streamer
              </p>
            </div>
          </div>

          {/* Primary navigation stays on the same header row to save vertical space. */}
          <nav className="hidden md:flex items-center gap-1.5 ml-5 mr-auto">
            <button
              onClick={() => setActiveTab('search')}
              className={activeTab === 'search'
                ? 'px-3.5 py-1.5 rounded-xl text-xs font-semibold flex items-center gap-2 transition bg-cyan-500 text-slate-950 shadow-md shadow-cyan-500/20'
                : 'px-3.5 py-1.5 rounded-xl text-xs font-semibold flex items-center gap-2 transition text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'}
            >
              <Search className="w-4 h-4" />
              <span>Search</span>
            </button>

            <button
              onClick={() => setActiveTab('files')}
              className={activeTab === 'files'
                ? 'px-3.5 py-1.5 rounded-xl text-xs font-semibold flex items-center gap-2 transition bg-cyan-500 text-slate-950 shadow-md shadow-cyan-500/20'
                : 'px-3.5 py-1.5 rounded-xl text-xs font-semibold flex items-center gap-2 transition text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'}
            >
              <Folder className="w-4 h-4" />
              <span>My Cloud Files</span>
              <span className="text-[10px] opacity-70">({files.length})</span>
            </button>
          </nav>

          {/* Right: Quick actions & User Switcher */}
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                setSeedrPat('');
                setSeedrConnectError('');
                setSeedrOnboardingOpen(true);
              }}
              className={seedrConnected
                ? "px-2.5 sm:px-4 py-1.5 sm:py-2 rounded-lg sm:rounded-xl bg-emerald-500/15 hover:bg-emerald-500/25 border border-emerald-500/30 text-emerald-300 text-xs sm:text-sm font-bold flex items-center gap-1.5 shadow-lg shadow-emerald-500/10 transition tap-target"
                : "px-2.5 sm:px-4 py-1.5 sm:py-2 rounded-lg sm:rounded-xl bg-gradient-to-r from-emerald-500 to-cyan-500 hover:from-emerald-400 hover:to-cyan-400 text-slate-950 text-xs sm:text-sm font-bold flex items-center gap-1.5 shadow-lg shadow-emerald-500/20 transition tap-target"}
              title={seedrConnected ? "Seedr is connected" : "Connect to Seedr"}
            >
              {seedrConnected ? <CheckCircle2 className="w-3.5 h-3.5 sm:w-4 sm:h-4" /> : <Cloud className="w-3.5 h-3.5 sm:w-4 sm:h-4" />}
              <span>{seedrConnected ? 'Seedr is Connected' : 'Connect to Seedr'}</span>
            </button>

            {/* Notification Bell */}
            <button
              onClick={() => setIsNotificationsOpen(true)}
              className="p-1.5 sm:p-2 rounded-lg sm:rounded-xl bg-slate-900 hover:bg-slate-800 text-slate-300 relative transition tap-target flex items-center justify-center border border-slate-800"
              title="Notifications & Push Alerts"
            >
              <Bell className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
              {unreadNotifsCount > 0 && (
                <span className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-cyan-500 text-slate-950 font-bold text-[9px] flex items-center justify-center">
                  {unreadNotifsCount}
                </span>
              )}
            </button>

            {/* Theme Toggle */}
            <button
              onClick={() => setTheme(theme === 'dark' ? 'dim' : 'dark')}
              className="p-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-slate-300 transition tap-target hidden sm:flex items-center justify-center border border-slate-800"
              title={`Theme: ${theme}`}
            >
              <Moon className="w-4 h-4 text-cyan-400" />
            </button>

          </div>
        </div>
      </header>
    </>
  );
}
