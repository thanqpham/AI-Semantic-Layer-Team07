'use client';

import { KeyRound, Link2 } from 'lucide-react';

import { Translated } from '@/components/ui/translated';
import { STATUS_ORDER, STATUS_STYLE } from '@/lib/relationshipGraph';

/** Floating legend explaining edge colors/dash patterns and column badges. */
export function DiagramLegend() {
  return (
    <div className="flex max-w-[calc(100vw-4rem)] flex-wrap items-center gap-x-3 gap-y-1.5 rounded-lg border border-border bg-card/90 px-3 py-2 text-[10px] text-muted-foreground shadow-sm backdrop-blur">
      {STATUS_ORDER.map((status) => {
        const style = STATUS_STYLE[status];
        return (
          <span key={status} className="inline-flex items-center gap-1.5">
            <svg width="22" height="6" aria-hidden="true">
              <line x1="1" y1="3" x2="21" y2="3" stroke={style.stroke} strokeWidth="2" strokeDasharray={style.dash} opacity={style.faded ? 0.6 : 1} />
            </svg>
            <Translated text={style.label} />
          </span>
        );
      })}
      <span className="h-3 w-px bg-border" aria-hidden="true" />
      <span className="inline-flex items-center gap-1"><KeyRound className="h-3 w-3 text-amber-500" />PK</span>
      <span className="inline-flex items-center gap-1"><Link2 className="h-3 w-3 text-sky-500" />FK</span>
    </div>
  );
}
