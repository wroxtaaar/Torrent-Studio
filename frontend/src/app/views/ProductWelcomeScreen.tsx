import { Cloud } from 'lucide-react';
import type { PanelModel } from '../useAppModel.tsx';

export function ProductWelcomeScreen({ vm }: { vm: PanelModel }) {
  const { setProductWelcomeOpen } = vm;
  return (
    <>
      <div className="min-h-screen bg-slate-950 text-slate-100 flex items-center justify-center px-6 py-10">
        <div className="w-full max-w-2xl text-center">
          <div className="mx-auto flex h-20 w-20 items-center justify-center rounded-3xl bg-gradient-to-tr from-cyan-500 via-blue-600 to-indigo-600 shadow-2xl shadow-cyan-500/20">
            <Cloud className="h-10 w-10 text-slate-950 fill-current" />
          </div>

          <p className="mt-8 text-xs font-bold uppercase tracking-[0.3em] text-cyan-400">
            Torrent Studio
          </p>
          <h1 className="mt-4 text-4xl font-black tracking-tight text-white sm:text-6xl">
            Welcome to Torrent Studio
          </h1>
          <p className="mx-auto mt-5 max-w-xl text-base leading-7 text-slate-400 sm:text-lg">
            Search torrents, explore releases, and discover everything you need before deciding where to download.
          </p>

          <button
            type="button"
            onClick={() => {
              try {
                window.localStorage.setItem('torrent_studio_welcome_seen', 'true');
              } catch {}
              setProductWelcomeOpen(false);
            }}
            className="mt-10 inline-flex min-w-44 items-center justify-center rounded-2xl bg-cyan-500 px-7 py-3.5 text-base font-bold text-slate-950 shadow-xl shadow-cyan-500/20 transition hover:bg-cyan-400"
          >
            Start Now
          </button>

          <p className="mt-5 text-xs text-slate-600">
            You can explore search without connecting a Seedr account.
          </p>
        </div>
      </div>
    </>
  );
}
