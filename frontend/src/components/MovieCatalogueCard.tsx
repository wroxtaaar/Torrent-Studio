import React from 'react';

type MovieCatalogueCardProps = {
  children: React.ReactNode;
  className?: string;
  onClick?: React.MouseEventHandler<HTMLElement>;
  /** Fired after the card is held down for about 0.7 s (no visible button on the card). */
  onLongPress?: () => void;
};

const HOLD_MS = 700;

/** Shared outer frame for movie catalogue cards. Catalogue-specific artwork,
 * metadata and actions remain in the caller; the common card surface lives here. */
export const MovieCatalogueCard: React.FC<MovieCatalogueCardProps> = ({ children, className = '', onClick, onLongPress }) => {
  const timer = React.useRef<number | null>(null);
  const fired = React.useRef(false);
  const start = React.useRef<{ x: number; y: number } | null>(null);
  const cancel = () => { if (timer.current !== null) { window.clearTimeout(timer.current); timer.current = null; } };
  const hold = onLongPress ? {
    onPointerDown: (event: React.PointerEvent<HTMLElement>) => {
      fired.current = false;
      start.current = { x: event.clientX, y: event.clientY };
      cancel();
      timer.current = window.setTimeout(() => { timer.current = null; fired.current = true; onLongPress(); }, HOLD_MS);
    },
    onPointerMove: (event: React.PointerEvent<HTMLElement>) => {
      const from = start.current;
      if (from && Math.hypot(event.clientX - from.x, event.clientY - from.y) > 10) cancel();
    },
    onPointerUp: cancel,
    onPointerLeave: cancel,
    onPointerCancel: cancel,
    // A touch long-press would otherwise open the browser's image menu on top of the report question.
    onContextMenu: (event: React.MouseEvent<HTMLElement>) => { if (fired.current || timer.current !== null) event.preventDefault(); },
  } : {};
  return (
    <article
      {...hold}
      onClick={event => {
        if (fired.current) { fired.current = false; return; }   // the press was a report, not a tap
        onClick?.(event);
      }}
      className={['min-w-0 overflow-hidden rounded-xl border border-slate-800 bg-slate-900 flex flex-col', className].filter(Boolean).join(' ')}
    >
      {children}
    </article>
  );
};
