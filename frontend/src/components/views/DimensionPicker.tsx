'use client';

import React, { useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, Copy, Link2, Target } from 'lucide-react';

import type { RecommendedDimensionItem } from '@/lib/api';
import { groupDimensions, joinPathLabel, TIER_TITLES, type DimensionTier } from '@/lib/dimensionGroups';
import { Translated } from '@/components/ui/translated';
import { useLanguage } from '@/context/LanguageContext';
import { cn } from '@/lib/utils';

interface DimensionPickerProps {
  items: RecommendedDimensionItem[];
  selectedIds: Set<number>;
  onToggle: (columnId: number) => void;
  /** Search results are not ranked by join distance, so they render as one flat list. */
  searching?: boolean;
}

interface PillProps {
  item: RecommendedDimensionItem;
  checked: boolean;
  onToggle: (columnId: number) => void;
  extraSources?: number;
}

function DimensionPill({ item, checked, onToggle, extraSources = 0 }: PillProps) {
  const { translate } = useLanguage();
  const path = joinPathLabel(item);
  const label = item.business_name || item.column_name;
  return (
    <button
      type="button"
      onClick={() => onToggle(item.column_id)}
      title={path ? `${translate('Đường nối')}: ${path}` : translate('Không cần nối bảng')}
      className={cn(
        'group inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-all cursor-pointer select-none',
        checked
          ? 'border-primary bg-primary text-primary-foreground shadow-2xs font-semibold'
          : 'border-border bg-background text-foreground hover:border-primary/60 hover:bg-accent/40',
      )}
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={() => {}}
        aria-label={label}
        className="h-3 w-3 rounded accent-primary pointer-events-none"
      />
      <span>{label}</span>
      <span
        className={cn(
          'rounded px-1 font-mono text-[9px]',
          checked ? 'bg-primary-foreground/20 text-primary-foreground' : 'bg-secondary text-muted-foreground',
        )}
      >
        {item.table_business_name}
      </span>
      {extraSources > 0 && (
        <span className={cn('inline-flex items-center gap-0.5 text-[10px]', checked ? '' : 'text-primary')}>
          <Copy className="h-2.5 w-2.5" aria-hidden="true" />+{extraSources}
        </span>
      )}
    </button>
  );
}

const TIER_ICON: Record<DimensionTier, React.ReactNode> = {
  A: <Target className="h-3 w-3" aria-hidden="true" />,
  B: <Link2 className="h-3 w-3" aria-hidden="true" />,
  C: <Link2 className="h-3 w-3" aria-hidden="true" />,
  D: <Link2 className="h-3 w-3" aria-hidden="true" />,
};

function GroupHeader({ tier }: { tier: DimensionTier }) {
  return (
    <p className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
      {TIER_ICON[tier]}
      <Translated text={TIER_TITLES[tier]} />
      {tier === 'A' && (
        <span className="normal-case font-normal tracking-normal">
          · <Translated text={'nên chọn trước'} />
        </span>
      )}
    </p>
  );
}

function AlternateRow({ item, checked, onToggle }: Omit<PillProps, 'extraSources'>) {
  const path = joinPathLabel(item);
  return (
    <div className="flex flex-wrap items-center gap-2">
      <DimensionPill item={item} checked={checked} onToggle={onToggle} />
      {path && <span className="text-[10px] text-muted-foreground">{path}</span>}
    </div>
  );
}

function AlternateSection({ items, selectedIds, onToggle }: Omit<DimensionPickerProps, 'searching'>) {
  const hasSelected = items.some((item) => selectedIds.has(item.column_id));
  const [open, setOpen] = useState(hasSelected);
  const expanded = open || hasSelected;
  return (
    <div className="border-t border-dashed border-border pt-2 space-y-1.5">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={expanded}
        className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground hover:text-foreground cursor-pointer"
      >
        {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        <Translated text={'Cùng tên, ở bảng khác'} /> ({items.length})
      </button>
      {expanded && (
        <div className="space-y-1.5 pl-4">
          <p className="text-[10px] text-muted-foreground">
            <Translated text={'Chỉ chọn khi bạn cần đúng cột ở bảng này; bản ở trên gần chỉ số hơn.'} />
          </p>
          {items.map((item) => (
            <AlternateRow
              key={item.column_id}
              item={item}
              checked={selectedIds.has(item.column_id)}
              onToggle={onToggle}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function FlatList({ items, selectedIds, onToggle }: Omit<DimensionPickerProps, 'searching'>) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((item) => (
        <DimensionPill
          key={item.column_id}
          item={item}
          checked={selectedIds.has(item.column_id)}
          onToggle={onToggle}
        />
      ))}
    </div>
  );
}

/** Dimension chooser grouped by join distance from the metric's base table. */
export function DimensionPicker({ items, selectedIds, onToggle, searching = false }: DimensionPickerProps) {
  const grouped = useMemo(() => groupDimensions(items), [items]);
  if (items.length === 0) {
    return (
      <p className="p-2 text-xs text-muted-foreground italic w-full text-center">
        <Translated text={'Không tìm thấy chiều phân tích phù hợp.'} />
      </p>
    );
  }
  if (searching) return <FlatList items={items} selectedIds={selectedIds} onToggle={onToggle} />;
  return (
    <div className="space-y-3">
      {grouped.groups.map((group) => (
        <div key={group.tier} className="space-y-1.5" data-testid={`dimension-group-${group.tier}`}>
          <GroupHeader tier={group.tier} />
          <div className="flex flex-wrap gap-1.5">
            {group.items.map((item) => (
              <DimensionPill
                key={item.column_id}
                item={item}
                checked={selectedIds.has(item.column_id)}
                onToggle={onToggle}
                extraSources={grouped.alternateCount.get(item.column_id) ?? 0}
              />
            ))}
          </div>
        </div>
      ))}
      {grouped.alternates.length > 0 && (
        <AlternateSection items={grouped.alternates} selectedIds={selectedIds} onToggle={onToggle} />
      )}
    </div>
  );
}
