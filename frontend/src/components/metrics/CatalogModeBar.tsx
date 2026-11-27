'use client';

import { cn } from '@/lib/utils';
import { Translated } from '@/components/ui/translated';

export type CatalogTab = 'approved' | 'pending' | 'submitted' | 'rejected' | 'trash' | 'audit';

export interface CatalogModeBarProps {
  value: CatalogTab;
  onChange: (tab: CatalogTab) => void;
  canManage: boolean;
  isMemberSubmitter: boolean;
  counts: { approved: number; pending: number; submitted: number; rejected: number; trash: number };
}

interface TabItem {
  key: CatalogTab;
  label: string;
  count?: number;
}

/**
 * Two primary modes (browse the catalog vs. work the review queue) plus a quiet
 * row of secondary views, so status filters no longer compete with tools.
 */
export function CatalogModeBar(props: CatalogModeBarProps) {
  const queue: TabItem | null = props.canManage
    ? { key: 'pending', label: 'Hàng chờ duyệt', count: props.counts.pending }
    : props.isMemberSubmitter
      ? { key: 'submitted', label: 'Đã gửi', count: props.counts.submitted }
      : null;
  const primary: TabItem[] = [{ key: 'approved', label: 'Danh mục', count: props.counts.approved }, ...(queue ? [queue] : [])];
  const secondary: TabItem[] = [
    ...(props.canManage || props.isMemberSubmitter ? [{ key: 'rejected' as const, label: 'Đã từ chối', count: props.counts.rejected }] : []),
    { key: 'audit', label: 'Audit' },
    ...(props.canManage ? [{ key: 'trash' as const, label: 'Thùng rác', count: props.counts.trash }] : []),
  ];
  return (
    <div className="flex flex-wrap items-center gap-3">
      <div role="group" aria-label="Chế độ danh mục" className="flex items-center gap-1 rounded-lg border border-border bg-secondary/60 p-1">
        {primary.map((item) => (
          <PrimaryTab key={item.key} item={item} active={props.value === item.key} highlight={item === queue} onSelect={props.onChange} />
        ))}
      </div>
      <div role="group" aria-label="Chế độ khác" className="flex items-center gap-1 text-xs">
        {secondary.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => props.onChange(item.key)}
            aria-pressed={props.value === item.key}
            className={cn(
              'cursor-pointer rounded-md px-2 py-1 transition-colors',
              props.value === item.key ? 'bg-secondary font-semibold text-foreground' : 'text-muted-foreground hover:text-foreground',
            )}
          >
            <Translated text={item.label} />
            {item.count !== undefined && <span className="ml-1 font-mono text-[10px]">({item.count})</span>}
          </button>
        ))}
      </div>
    </div>
  );
}

function PrimaryTab({ item, active, highlight, onSelect }: {
  item: TabItem;
  active: boolean;
  highlight: boolean;
  onSelect: (tab: CatalogTab) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onSelect(item.key)}
      aria-pressed={active}
      className={cn(
        'flex cursor-pointer items-center gap-1.5 rounded-md px-3 py-1.5 text-xs transition-colors',
        active ? 'bg-card font-semibold text-foreground shadow-xs' : 'text-muted-foreground hover:text-foreground',
      )}
    >
      <Translated text={item.label} />
      <span
        className={cn(
          'rounded-full px-1.5 font-mono text-[10px]',
          highlight && (item.count ?? 0) > 0 ? 'bg-amber-500/15 text-amber-600 dark:text-amber-400' : 'bg-secondary text-secondary-foreground',
        )}
      >
        ({item.count ?? 0})
      </span>
    </button>
  );
}
