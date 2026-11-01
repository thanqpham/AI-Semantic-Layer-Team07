'use client';

import { AlertTriangle, ArrowRight, ChevronDown, Network, Table2 } from 'lucide-react';
import { useMemo, useState } from 'react';

import { Translated } from '@/components/ui/translated';
import { useLanguage } from '@/context/LanguageContext';
import { CARDINALITY, readPairs, relationshipKey, statusStyle } from '@/lib/relationshipGraph';
import { qualifiedEntity, type RelationshipEntity, type RelationshipItem } from '@/lib/relationshipReviewApi';
import { cn } from '@/lib/utils';
import { RelationshipStatusBadge } from './RelationshipStatusBadge';

interface Props {
  items: RelationshipItem[];
  selectedKey: string | null;
  loading: boolean;
  onOpen: (item: RelationshipItem, trigger: HTMLButtonElement) => void;
}

interface TableGroup {
  entity: RelationshipEntity;
  label: string;
  items: RelationshipItem[];
  pendingCount: number;
  approvedCount: number;
}

function groupByTable(items: RelationshipItem[]): TableGroup[] {
  const map = new Map<string, TableGroup>();
  for (const item of items) {
    const label = qualifiedEntity(item.from_entity);
    const key = `${item.from_entity.id}:${label}`;
    let group = map.get(key);
    if (!group) {
      group = {
        entity: item.from_entity,
        label,
        items: [],
        pendingCount: 0,
        approvedCount: 0,
      };
      map.set(key, group);
    }
    group.items.push(item);
    if (item.status === 'pending_review' || item.status === 'needs_review') {
      group.pendingCount += 1;
    } else if (item.status === 'approved') {
      group.approvedCount += 1;
    }
  }
  return Array.from(map.values());
}

function pairPreview(item: RelationshipItem): string[] {
  const fromCols = new Map(item.from_entity.columns.map((col) => [col.id, col.name]));
  const toCols = new Map(item.to_entity.columns.map((col) => [col.id, col.name]));
  return readPairs(item)
    .map((p) => {
      const src = fromCols.get(p.from_column_id);
      const tgt = toCols.get(p.to_column_id);
      return src && tgt ? `${src} → ${tgt}` : null;
    })
    .filter((v): v is string => Boolean(v));
}

function RelationshipCard({
  item,
  index,
  selected,
  onOpen,
}: {
  item: RelationshipItem;
  index: number;
  selected: boolean;
  onOpen: Props['onOpen'];
}) {
  const { translate: t } = useLanguage();
  const pairs = readPairs(item).length;
  const colPairs = pairPreview(item);
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={(event) => onOpen(item, event.currentTarget)}
      style={{ borderLeftColor: statusStyle(item.status).stroke }}
      className={cn(
        'group w-full break-words rounded-lg border border-l-4 border-border bg-background/70 p-3 text-left text-sm shadow-2xs transition-all hover:bg-accent/40 hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500',
        selected && 'bg-sky-500/5 ring-2 ring-sky-500/50',
      )}
    >
      <span className="flex flex-wrap items-center gap-1.5 font-mono text-[12px]">
        <span className="inline-flex h-4 min-w-4 shrink-0 items-center justify-center rounded bg-muted px-1 font-mono text-[10px] text-muted-foreground">
          {index + 1}
        </span>
        <span className="font-semibold text-muted-foreground">{qualifiedEntity(item.from_entity)}</span>
        <ArrowRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
        <span className="font-semibold text-foreground">{qualifiedEntity(item.to_entity)}</span>
      </span>
      {colPairs.length > 0 && (
        <span className="mt-1.5 block truncate rounded bg-muted/60 px-2 py-1 font-mono text-[11px] text-muted-foreground">
          {colPairs.join(', ')}
        </span>
      )}
      <span className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
        <RelationshipStatusBadge status={item.status} />
        <span className="rounded bg-muted px-1.5 py-0.5 font-mono">{CARDINALITY[item.relationship_type]}</span>
        <span className="font-mono uppercase">{item.source}</span>
        {pairs > 1 && <span>{pairs} {t('cặp cột')}</span>}
        {item.errors.length > 0 && <span className="inline-flex items-center gap-1 text-destructive"><AlertTriangle className="h-3 w-3" aria-hidden="true" />{item.errors.length}</span>}
        <span className="ml-auto font-mono">#{item.id}</span>
      </span>
    </button>
  );
}

/** Grouped relationship list by source table (alternative to the diagram view). */
export function RelationshipCardList({ items, selectedKey, loading, onOpen }: Props) {
  const { translate: t } = useLanguage();
  const groups = useMemo(() => groupByTable(items), [items]);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  if (!loading && !items.length) {
    return (
      <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
        <Network className="h-5 w-5" aria-hidden="true" />
        <p><Translated text="Chưa có liên kết." /></p>
      </div>
    );
  }

  return (
    <div className="space-y-4" aria-label={t('Danh sách liên kết')}>
      {groups.map((group, groupIndex) => {
        const groupKey = `${group.entity.id}:${group.label}`;
        const isOpen = !collapsed[groupKey];
        return (
          <section
            key={groupKey}
            className="overflow-hidden rounded-xl border border-border bg-card shadow-xs"
          >
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-muted/40 px-4 py-2.5">
              <button
                type="button"
                aria-expanded={isOpen}
                onClick={() => setCollapsed((prev) => ({ ...prev, [groupKey]: !prev[groupKey] }))}
                className="flex min-w-0 items-center gap-2 text-left"
              >
                <ChevronDown
                  className={cn('h-4 w-4 shrink-0 text-muted-foreground transition-transform', !isOpen && '-rotate-90')}
                  aria-hidden="true"
                />
                <span className="inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded bg-secondary px-1.5 font-mono text-[10px] font-semibold text-secondary-foreground">
                  #{groupIndex + 1}
                </span>
                <Table2 className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
                <span className="truncate font-mono text-[13px] font-semibold text-foreground">
                  {group.label}
                </span>
              </button>
              <div className="flex flex-wrap items-center gap-2 text-[11px]">
                {group.entity.id > 0 && (
                  <span className="rounded border border-border bg-background px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                    Table ID: {group.entity.id}
                  </span>
                )}
                {group.pendingCount > 0 && (
                  <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 font-mono text-[10px] text-amber-700 dark:text-amber-400">
                    {group.pendingCount} {t('chờ review')}
                  </span>
                )}
                {group.approvedCount > 0 && (
                  <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 font-mono text-[10px] text-emerald-600 dark:text-emerald-400">
                    {group.approvedCount} {t('đã duyệt')}
                  </span>
                )}
                <span className="rounded-full bg-secondary px-2 py-0.5 font-mono text-[10px] text-secondary-foreground">
                  {group.items.length} {t('liên kết')}
                </span>
              </div>
            </div>

            {isOpen && (
              <div className="grid min-w-0 gap-2.5 p-3 xl:grid-cols-2">
                {group.items.map((item, idx) => (
                  <RelationshipCard
                    key={relationshipKey(item)}
                    item={item}
                    index={idx}
                    selected={selectedKey === relationshipKey(item)}
                    onOpen={onOpen}
                  />
                ))}
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}
