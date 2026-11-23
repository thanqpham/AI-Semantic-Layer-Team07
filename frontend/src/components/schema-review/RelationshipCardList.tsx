'use client';

import { AlertTriangle, ArrowRight, CheckCircle2, Network, Table2 } from 'lucide-react';
import { useMemo, useState, type ReactNode } from 'react';

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
  /** Relationship detail editor; when set it replaces the table's list in the right pane. */
  detail?: ReactNode;
  /** Close the open detail (guarding unsaved edits), then run *next*. */
  onLeaveDetail?: (next: () => void) => void;
}

interface TableNode {
  entity: RelationshipEntity;
  label: string;
  outgoing: RelationshipItem[];
  incoming: RelationshipItem[];
  pending: number;
}

const isPending = (item: RelationshipItem) => item.status === 'pending_review' || item.status === 'needs_review';

/** Index every table touching a relationship, with its outgoing and incoming edges. */
function buildTables(items: RelationshipItem[]): TableNode[] {
  const map = new Map<number, TableNode>();
  const node = (entity: RelationshipEntity) => {
    let found = map.get(entity.id);
    if (!found) map.set(entity.id, (found = { entity, label: qualifiedEntity(entity), outgoing: [], incoming: [], pending: 0 }));
    return found;
  };
  for (const item of items) {
    const from = node(item.from_entity);
    from.outgoing.push(item);
    if (isPending(item)) from.pending += 1;
    if (item.to_entity.id === item.from_entity.id) continue;
    const to = node(item.to_entity);
    to.incoming.push(item);
    if (isPending(item)) to.pending += 1;
  }
  return Array.from(map.values()).sort((a, b) => a.label.localeCompare(b.label));
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

function RelationshipCard({ item, selected, onOpen }: { item: RelationshipItem; selected: boolean; onOpen: Props['onOpen'] }) {
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
        <span className="font-semibold text-muted-foreground">{qualifiedEntity(item.from_entity)}</span>
        <ArrowRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
        <span className="font-semibold text-foreground">{qualifiedEntity(item.to_entity)}</span>
      </span>
      {colPairs.length > 0 && (
        <span className="mt-1.5 block truncate rounded bg-muted/60 px-2 py-1 font-mono text-[11px] text-muted-foreground">{colPairs.join(', ')}</span>
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

function TableTreeList({ tables, activeId, onActivate }: { tables: TableNode[]; activeId: number | undefined; onActivate: (id: number) => void }) {
  const { translate: t } = useLanguage();
  return (
    <nav aria-label={t('Bảng có liên kết')} className="flex min-w-0 flex-col gap-2 rounded-xl border border-border bg-card p-3 md:sticky md:top-0 md:max-h-[calc(100vh-12rem)]">
      <p className="px-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        <Translated text={'Bảng có liên kết'} after />· {tables.length}
      </p>
      <ul className="-mx-1 min-h-0 flex-1 space-y-0.5 overflow-y-auto">
        {tables.map((table) => {
          const active = table.entity.id === activeId;
          return (
            <li key={table.entity.id}>
              <button type="button" onClick={() => onActivate(table.entity.id)} aria-current={active ? 'true' : undefined}
                className={cn('flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left', active ? 'bg-primary/10 text-primary' : 'hover:bg-secondary')}>
                <span className="min-w-0 truncate font-mono text-xs">{table.label}</span>
                {table.pending > 0 ? (
                  <span className="shrink-0 rounded-full bg-amber-500/15 px-2 py-0.5 font-mono text-[10px] text-amber-700 dark:text-amber-300">{table.pending}</span>
                ) : (
                  <CheckCircle2 aria-label="Không còn liên kết chờ" className="h-3.5 w-3.5 shrink-0 text-emerald-500" />
                )}
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

function EdgeSection({ title, items, selectedKey, onOpen }: { title: string; items: RelationshipItem[]; selectedKey: string | null; onOpen: Props['onOpen'] }) {
  if (!items.length) return null;
  return (
    <div className="space-y-2">
      <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground"><Translated text={title} after />· {items.length}</p>
      <div className="grid min-w-0 gap-2.5 2xl:grid-cols-2">
        {items.map((item) => (
          <RelationshipCard key={relationshipKey(item)} item={item} selected={selectedKey === relationshipKey(item)} onOpen={onOpen} />
        ))}
      </div>
    </div>
  );
}

function TableEdges({ table, selectedKey, onOpen }: { table: TableNode; selectedKey: string | null; onOpen: Props['onOpen'] }) {
  const { translate: t } = useLanguage();
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Table2 className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        <span className="truncate font-mono text-sm font-semibold text-foreground">{table.label}</span>
        {table.entity.id > 0 && (
          <span className="rounded border border-border px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">Table ID: {table.entity.id}</span>
        )}
        <span className="text-xs text-muted-foreground">
          {table.outgoing.length} {t('liên kết đi')} · {table.incoming.length} {t('liên kết đến')}
        </span>
      </div>
      <EdgeSection title="Liên kết đi" items={table.outgoing} selectedKey={selectedKey} onOpen={onOpen} />
      <EdgeSection title="Liên kết đến" items={table.incoming} selectedKey={selectedKey} onOpen={onOpen} />
    </div>
  );
}

/** Two-pane relationship list: tables on the left, the selected table's relationships (or the detail editor) on the right. */
export function RelationshipCardList({ items, selectedKey, loading, onOpen, detail, onLeaveDetail }: Props) {
  const { translate: t } = useLanguage();
  const tables = useMemo(() => buildTables(items), [items]);
  const [activeId, setActiveId] = useState<number | null>(null);
  // Default to a source table with pending edges, so the first view shows something to review.
  const active =
    tables.find((table) => table.entity.id === activeId) ??
    tables.find((table) => table.outgoing.some(isPending)) ??
    tables.find((table) => table.pending > 0) ??
    tables[0];

  if (!loading && !items.length && !detail) {
    return (
      <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
        <Network className="h-5 w-5" aria-hidden="true" />
        <p><Translated text="Chưa có liên kết." /></p>
      </div>
    );
  }

  return (
    <div className="grid items-start gap-4 md:grid-cols-[minmax(220px,280px)_minmax(0,1fr)]" aria-label={t('Danh sách liên kết')}>
      <TableTreeList tables={tables} activeId={active?.entity.id}
        onActivate={(id) => (detail && onLeaveDetail ? onLeaveDetail(() => setActiveId(id)) : setActiveId(id))} />
      <div className="min-w-0">
        {/* The list stays mounted while the detail is open so focus can return to the row that opened it. */}
        <section hidden={Boolean(detail)} aria-label={active?.label} className="rounded-xl border border-border bg-card p-4 shadow-sm">
          {active && <TableEdges table={active} selectedKey={selectedKey} onOpen={onOpen} />}
        </section>
        {detail}
      </div>
    </div>
  );
}
