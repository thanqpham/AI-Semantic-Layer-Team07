import { Translated } from '@/components/ui/translated';
import { statusStyle } from '@/lib/relationshipGraph';
import { cn } from '@/lib/utils';

const TONES: Record<string, { pill: string; dot: string }> = {
  amber: { pill: 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300', dot: 'bg-amber-500' },
  emerald: { pill: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300', dot: 'bg-emerald-500' },
  orange: { pill: 'border-orange-500/30 bg-orange-500/10 text-orange-700 dark:text-orange-300', dot: 'bg-orange-500' },
  red: { pill: 'border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300', dot: 'bg-red-500' },
  zinc: { pill: 'border-zinc-500/30 bg-zinc-500/10 text-zinc-600 dark:text-zinc-300', dot: 'bg-zinc-400' },
};

/** Tailwind classes for a status tone (static strings so Tailwind can detect them). */
export function statusTone(status: string): { pill: string; dot: string } {
  return TONES[statusStyle(status).tone] ?? TONES.amber;
}

/** Colored pill showing a relationship's review status. */
export function RelationshipStatusBadge({ status, className }: { status: string; className?: string }) {
  const tone = statusTone(status);
  return (
    <span className={cn('inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 text-[10px] font-medium', tone.pill, className)}>
      <span className={cn('h-1.5 w-1.5 rounded-full', tone.dot)} />
      <Translated text={statusStyle(status).label} />
      <span className="sr-only">{status}</span>
    </span>
  );
}
