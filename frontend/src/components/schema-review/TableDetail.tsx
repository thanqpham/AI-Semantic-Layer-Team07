'use client';

import { CheckCircle2, Loader2, Sparkles } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import type { SchemaReviewColumn, SchemaReviewTable } from '@/lib/api';
import { cn } from '@/lib/utils';
import { Translated } from '@/components/ui/translated';
import { useLanguage } from '@/context/LanguageContext';
import { ColumnValueEditor } from './ColumnValueProposals';

export type Draft = { business_name: string; description: string };
export type DraftMap = Record<string, Draft>;

export function tableKey(table: SchemaReviewTable): string {
  return `t:${table.table_id}`;
}

export function columnKey(table: SchemaReviewTable, column: SchemaReviewColumn): string {
  return `c:${table.table_id}:${column.column_id}`;
}

/** Badge showing whether a metadata row is officially stored or still in review. */
export function ReviewBadge({ status }: { status: 'pending_review' | 'approved' }) {
  const approved = status === 'approved';
  return (
    <span className={cn('inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 font-mono text-[10px]',
      approved ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
        : 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-400')}>
      <span className={cn('h-1.5 w-1.5 rounded-full', approved ? 'bg-emerald-500' : 'bg-amber-500')} />
      <Translated text={approved ? 'Đã lưu chính thức' : 'Chờ review'} />
    </span>
  );
}

interface RowEditorProps {
  draft?: Draft;
  aiBusinessName?: string | null;
  disabled?: boolean;
  dirty?: boolean;
  onChange: (patch: Partial<Draft>) => void;
}

/** Inline editor for one table or column row; changes are saved by "Lưu tất cả". */
function RowEditor({ draft, aiBusinessName, disabled, dirty, onChange }: RowEditorProps) {
  const { translate } = useLanguage();
  const name = draft?.business_name ?? '';
  const dirtyClass = dirty ? 'border-amber-500/60 bg-amber-500/5' : '';
  return (
    <div className="grid flex-1 gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
      <div className="min-w-0">
        <Input value={name} disabled={disabled} placeholder={translate('Tên nghiệp vụ')} className={cn('h-8 text-xs', dirtyClass)}
          onChange={(event) => onChange({ business_name: event.target.value })} />
        {aiBusinessName && aiBusinessName !== name && (
          <button type="button" disabled={disabled} onClick={() => onChange({ business_name: aiBusinessName })} title={translate('Dùng đề xuất của AI')}
            className="mt-1 inline-flex items-center gap-1.5 text-left font-mono text-[10px] text-muted-foreground transition-colors hover:text-primary disabled:opacity-50">
            <Sparkles className="h-3 w-3 shrink-0" />
            <span className="truncate"><Translated text={'AI đề xuất:'} after />{aiBusinessName}</span>
          </button>
        )}
      </div>
      <Input value={draft?.description ?? ''} disabled={disabled} placeholder={translate('Mô tả nghiệp vụ')} className={cn('h-8 text-xs', dirtyClass)}
        onChange={(event) => onChange({ description: event.target.value })} />
    </div>
  );
}

/** A row counts as empty when the AI has nothing to show for it yet. */
function cellIsEmpty(draft: Draft | undefined, physicalName: string): boolean {
  return (draft?.description ?? '') === '' && (!draft?.business_name || draft.business_name === physicalName);
}

function SkeletonCell() {
  return <div className="h-8 flex-1 animate-pulse rounded bg-muted" aria-hidden="true" />;
}

interface TableDetailProps {
  dbId: number;
  table: SchemaReviewTable;
  label: string;
  hidden: boolean;
  drafts: DraftMap;
  approving: string | null;
  canManageSchema: boolean;
  canApproveSchema: boolean;
  enriching: boolean;
  isDirty: (key: string) => boolean;
  patch: (key: string, value: Partial<Draft>) => void;
  approve: (tableIds?: number[]) => Promise<void>;
  onReviewChanged?: () => void;
}

/** Right-hand panel: one table's metadata, its columns, and bulk column actions. */
export function TableDetail(props: TableDetailProps) {
  const { table, hidden, drafts, canManageSchema, enriching, isDirty, patch } = props;
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const key = tableKey(table);
  return (
    <section hidden={hidden} aria-label={props.label} className="min-w-0 space-y-4 rounded-xl border border-border bg-card p-4 shadow-sm">
      <DetailHeader {...props} />
      {enriching && cellIsEmpty(drafts[key], table.table_name) ? <SkeletonCell /> : (
        <RowEditor draft={drafts[key]} aiBusinessName={table.ai_business_name} disabled={!canManageSchema}
          dirty={isDirty(key)} onChange={(value) => patch(key, value)} />
      )}
      <ColumnBulkBar table={table} picked={picked} setPicked={setPicked} disabled={!canManageSchema} patch={patch} />
      <div className="space-y-3 border-t border-border pt-3">
        {table.columns.map((column, index) => (
          <ColumnRow key={column.column_id} {...props} column={column} index={index}
            checked={picked.has(column.column_id)} onToggle={() => setPicked(toggle(picked, column.column_id))} />
        ))}
      </div>
    </section>
  );
}

function toggle(set: Set<number>, id: number): Set<number> {
  const next = new Set(set);
  if (next.has(id)) next.delete(id); else next.add(id);
  return next;
}

function DetailHeader({ table, label, approving, canApproveSchema, approve }: TableDetailProps) {
  const pendingColumns = table.columns.filter((c) => c.review_status === 'pending_review').length;
  return (
    <div className="flex flex-wrap items-center gap-3">
      <h3 className="truncate font-mono text-sm font-semibold text-foreground">{label}</h3>
      <span className="rounded border border-border px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">Table ID: {table.table_id}</span>
      <ReviewBadge status={table.review_status} />
      <span className="font-mono text-[10px] text-muted-foreground">
        {pendingColumns}/{table.columns.length} <Translated text={'cột chờ'} />
      </span>
      {table.reviewed_at && (
        <span className="font-mono text-[10px] text-muted-foreground">
          <Translated text={'Duyệt lúc'} after />{new Date(table.reviewed_at).toLocaleString()}
        </span>
      )}
      <Button size="sm" variant="outline" className="ml-auto h-8 gap-1.5 text-[11px]" onClick={() => approve([table.table_id])}
        disabled={!canApproveSchema || approving !== null || (table.review_status === 'approved' && pendingColumns === 0)}>
        {approving === String(table.table_id) ? <Loader2 className="h-3 w-3 animate-spin" /> : <CheckCircle2 className="h-3 w-3" />}
        <Translated text={'Duyệt bảng này'} />
      </Button>
    </div>
  );
}

interface BulkBarProps {
  table: SchemaReviewTable;
  picked: Set<number>;
  setPicked: (next: Set<number>) => void;
  disabled: boolean;
  patch: (key: string, value: Partial<Draft>) => void;
}

/** Select-all toggle plus "accept AI" for the ticked columns (fills drafts only). */
function ColumnBulkBar({ table, picked, setPicked, disabled, patch }: BulkBarProps) {
  const allPicked = table.columns.length > 0 && picked.size === table.columns.length;
  const acceptAi = () => {
    for (const column of table.columns) {
      if (!picked.has(column.column_id) || !column.ai_business_name) continue;
      patch(columnKey(table, column), {
        business_name: column.ai_business_name,
        ...(column.ai_description ? { description: column.ai_description } : {}),
      });
    }
    setPicked(new Set());
  };
  return (
    <div className="flex flex-wrap items-center gap-3 text-xs">
      <label className="inline-flex items-center gap-2">
        <input type="checkbox" checked={allPicked} disabled={disabled || table.columns.length === 0}
          onChange={() => setPicked(allPicked ? new Set() : new Set(table.columns.map((c) => c.column_id)))} />
        <Translated text={'Chọn tất cả cột'} />
      </label>
      <Button size="sm" variant="outline" className="h-7 gap-1.5 text-[11px]" disabled={disabled || picked.size === 0} onClick={acceptAi}>
        <Sparkles className="h-3 w-3" />
        <Translated text={'Chấp nhận AI cho'} after />{picked.size} <Translated text={'cột'} />
      </Button>
    </div>
  );
}

type ColumnRowProps = TableDetailProps & { column: SchemaReviewColumn; index: number; checked: boolean; onToggle: () => void };

function ColumnRow({ dbId, table, column, index, checked, onToggle, drafts, canManageSchema, canApproveSchema, enriching, isDirty, patch, onReviewChanged }: ColumnRowProps) {
  const key = columnKey(table, column);
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <input type="checkbox" checked={checked} disabled={!canManageSchema} onChange={onToggle} aria-label={`Chọn cột ${column.column_name}`} />
        <span className="inline-flex h-4 min-w-4 items-center justify-center rounded bg-muted px-1 font-mono text-[10px] text-muted-foreground">{index + 1}</span>
        <span className="truncate font-mono text-[11px] text-muted-foreground">
          {column.column_name}<span className="ml-1.5 opacity-60">{column.data_type}</span>
        </span>
        <span className="rounded border border-border px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">Column ID: {column.column_id}</span>
        {column.is_primary_key && <span className="rounded bg-secondary px-1.5 font-mono text-[9px] text-secondary-foreground">PK</span>}
        <ReviewBadge status={column.review_status} />
        {(column.pending_value_count ?? 0) > 0 && <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-800 dark:bg-amber-900 dark:text-amber-100">● {column.pending_value_count} giá trị chờ duyệt</span>}
      </div>
      {enriching && cellIsEmpty(drafts[key], column.column_name) ? <SkeletonCell /> : (
        <RowEditor draft={drafts[key]} aiBusinessName={column.ai_business_name} disabled={!canManageSchema}
          dirty={isDirty(key)} onChange={(value) => patch(key, value)} />
      )}
      <ColumnValueEditor dbId={String(dbId)} columnId={column.column_id} columnName={column.column_name}
        canManage={canManageSchema} canApprove={canApproveSchema} onReviewChanged={onReviewChanged} />
    </div>
  );
}
