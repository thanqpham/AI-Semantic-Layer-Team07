'use client';

import { CheckCircle2, Database, Loader2 } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import type { SchemaReviewTable } from '@/lib/api';
import { cn } from '@/lib/utils';
import { Translated } from '@/components/ui/translated';
import { useLanguage } from '@/context/LanguageContext';

/** Rows of *table* still awaiting review: the table itself, its columns, and its values. */
export function pendingCount(table: SchemaReviewTable): number {
  const columns = table.columns.filter((column) => column.review_status === 'pending_review').length;
  const values = table.columns.reduce((total, column) => total + (column.pending_value_count ?? 0), 0);
  return (table.review_status === 'pending_review' ? 1 : 0) + columns + values;
}

/** Qualify a table name with its schema only when the bare name is ambiguous. */
export function tableLabel(table: SchemaReviewTable, tables: SchemaReviewTable[]): string {
  const duplicate = tables.filter((item) => item.table_name === table.table_name).length > 1;
  return duplicate && table.physical_schema ? `${table.physical_schema}.${table.table_name}` : table.table_name;
}

/** The database itself, pinned above the tables so its overview opens in the same detail pane. */
export interface TreeDatabaseItem {
  label: string;
  described: boolean | null;
  active: boolean;
  onActivate: () => void;
}

interface TableTreeProps {
  database: TreeDatabaseItem;
  tables: SchemaReviewTable[];
  activeId: number | null;
  onActivate: (tableId: number) => void;
  selected: Set<number>;
  onSelectedChange: (next: Set<number>) => void;
  canApprove: boolean;
  approving: string | null;
  onApproveSelected: () => void;
}

/** Left-hand list of tables with search, a pending-only filter, and multi-select approval. */
export function TableTree({ database, tables, activeId, onActivate, selected, onSelectedChange, canApprove, approving, onApproveSelected }: TableTreeProps) {
  const { translate } = useLanguage();
  const [query, setQuery] = useState('');
  const [pendingOnly, setPendingOnly] = useState(false);
  const needle = query.trim().toLowerCase();
  const visible = tables.filter((table) =>
    (!pendingOnly || pendingCount(table) > 0) &&
    (!needle || `${table.table_name} ${table.business_name}`.toLowerCase().includes(needle)));
  const allVisibleSelected = visible.length > 0 && visible.every((table) => selected.has(table.table_id));
  const toggleVisible = () => {
    const next = new Set(selected);
    for (const table of visible) if (allVisibleSelected) next.delete(table.table_id); else next.add(table.table_id);
    onSelectedChange(next);
  };
  return (
    <nav aria-label={translate('Danh sách bảng')} className="flex min-w-0 flex-col gap-2 rounded-xl border border-border bg-card p-3 md:sticky md:top-0 md:max-h-[calc(100vh-12rem)]">
      <p className="px-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        <Translated text={'Tổng quan database'} />
      </p>
      <DatabaseEntry {...database} />
      <p className="px-1 pt-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        <Translated text={'Bảng'} after />· {tables.length}
      </p>
      <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={translate('Tìm bảng…')} aria-label={translate('Tìm bảng')} className="h-8 text-xs" />
      <div className="flex flex-wrap items-center gap-3 text-xs">
        <label className="inline-flex items-center gap-2">
          <input type="checkbox" checked={allVisibleSelected} disabled={visible.length === 0} onChange={toggleVisible} />
          <Translated text={'Chọn tất cả'} />
        </label>
        <label className="inline-flex items-center gap-2">
          <input type="checkbox" checked={pendingOnly} onChange={() => setPendingOnly(!pendingOnly)} />
          <Translated text={'Chỉ chờ review'} />
        </label>
      </div>
      <ul className="-mx-1 min-h-0 flex-1 space-y-0.5 overflow-y-auto">
        {visible.map((table) => (
          <TreeItem key={table.table_id} table={table} label={tableLabel(table, tables)} active={table.table_id === activeId}
            checked={selected.has(table.table_id)} onActivate={() => onActivate(table.table_id)}
            onToggle={() => onSelectedChange(toggleId(selected, table.table_id))} />
        ))}
        {visible.length === 0 && <li className="px-2 py-3 text-xs text-muted-foreground"><Translated text={'Không có bảng phù hợp.'} /></li>}
      </ul>
      <Button size="sm" className="gap-2 text-xs" onClick={onApproveSelected} disabled={!canApprove || selected.size === 0 || approving !== null}>
        {approving === 'selected' ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
        <Translated text={'Duyệt'} after />{selected.size} <Translated text={'bảng đã chọn'} />
      </Button>
    </nav>
  );
}

function DatabaseEntry({ label, described, active, onActivate }: TreeDatabaseItem) {
  return (
    <button type="button" onClick={onActivate} aria-current={active ? 'true' : undefined}
      className={cn('flex items-center gap-2 rounded-md px-2 py-2 text-left', active ? 'bg-primary/10 text-primary' : 'hover:bg-secondary')}>
      <Database className="h-4 w-4 shrink-0" aria-hidden="true" />
      <span className="min-w-0 flex-1 truncate text-xs font-semibold">{label}</span>
      {described === false && (
        <span className="shrink-0 rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] text-amber-700 dark:text-amber-300">
          <Translated text={'Chưa mô tả'} />
        </span>
      )}
      {described && <CheckCircle2 aria-label="Đã mô tả" className="h-3.5 w-3.5 shrink-0 text-emerald-500" />}
    </button>
  );
}

function toggleId(set: Set<number>, id: number): Set<number> {
  const next = new Set(set);
  if (next.has(id)) next.delete(id); else next.add(id);
  return next;
}

interface TreeItemProps {
  table: SchemaReviewTable;
  label: string;
  active: boolean;
  checked: boolean;
  onActivate: () => void;
  onToggle: () => void;
}

function TreeItem({ table, label, active, checked, onActivate, onToggle }: TreeItemProps) {
  const pending = pendingCount(table);
  return (
    <li className={cn('flex items-center gap-2 rounded-md px-2 py-1.5', active ? 'bg-primary/10 text-primary' : 'hover:bg-secondary')}>
      <input type="checkbox" checked={checked} onChange={onToggle} aria-label={`Chọn bảng ${label}`} />
      <button type="button" onClick={onActivate} aria-current={active ? 'true' : undefined} className="flex min-w-0 flex-1 items-center justify-between gap-2 text-left">
        <span className="min-w-0">
          <span className="block truncate font-mono text-xs">{label}</span>
          {table.business_name && table.business_name !== table.table_name && (
            <span className="block truncate text-[10px] text-muted-foreground">{table.business_name}</span>
          )}
        </span>
        {pending > 0 ? (
          <span className="shrink-0 rounded-full bg-amber-500/15 px-2 py-0.5 font-mono text-[10px] text-amber-700 dark:text-amber-300">{pending}</span>
        ) : (
          <CheckCircle2 aria-label="Đã duyệt" className="h-3.5 w-3.5 shrink-0 text-emerald-500" />
        )}
      </button>
    </li>
  );
}
