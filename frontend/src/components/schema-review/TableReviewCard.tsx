'use client';

import { Check, CheckCircle2, ChevronRight, Loader2, Sparkles } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  updateColumnReviewApi,
  updateTableReviewApi,
  type SchemaReview,
  type SchemaReviewColumn,
  type SchemaReviewTable,
} from '@/lib/api';
import { cn } from '@/lib/utils';
import { Translated } from '@/components/ui/translated';
import { useLanguage } from '@/context/LanguageContext';

export type Draft = { business_name: string; description: string; allowed_values?: string };
export type DraftMap = Record<string, Draft>;

export function tableKey(table: SchemaReviewTable): string {
  return `t:${table.table_id}`;
}

export function columnKey(table: SchemaReviewTable, column: SchemaReviewColumn): string {
  return `c:${table.table_id}:${column.column_id}`;
}

/** Badge showing whether a metadata row is officially stored or still in review. */
function ReviewBadge({ status }: { status: 'pending_review' | 'approved' }) {
  const approved = status === 'approved';
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 font-mono text-[10px]',
        approved
          ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
          : 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-400',
      )}
    >
      <span className={cn('h-1.5 w-1.5 rounded-full', approved ? 'bg-emerald-500' : 'bg-amber-500')} />
      <Translated text={approved ? 'Đã lưu chính thức' : 'Chờ review'} />
    </span>
  );
}

/** Show the AI proposal only when it differs from the value the reviewer sees. */
function AiSuggestion({
  suggestion,
  current,
  onAccept,
  disabled,
}: {
  suggestion?: string | null;
  current: string;
  onAccept: () => void;
  disabled?: boolean;
}) {
  const { translate } = useLanguage();
  if (!suggestion || suggestion === current) return null;
  return (
    <button
      type="button"
      onClick={onAccept}
      disabled={disabled}
      className="mt-1 inline-flex items-center gap-1.5 text-left font-mono text-[10px] text-muted-foreground transition-colors hover:text-primary disabled:opacity-50"
      title={translate("Dùng đề xuất của AI")}
    >
      <Sparkles className="h-3 w-3 shrink-0" />
      <span className="truncate"><Translated text={"AI đề xuất:"} after />{suggestion}</span>
    </button>
  );
}

/** Inline editor for one table or column row. */
function RowEditor({
  businessName,
  description,
  allowedValues,
  aiBusinessName,
  disabled,
  saving,
  dirty,
  onChange,
  onSave,
}: {
  businessName: string;
  description: string;
  allowedValues?: string;
  aiBusinessName?: string | null;
  disabled?: boolean;
  saving?: boolean;
  dirty?: boolean;
  onChange: (patch: Partial<Draft>) => void;
  onSave: () => void;
}) {
  const { translate } = useLanguage();
  return (
    <div className={cn(
      'grid flex-1 gap-2',
      allowedValues === undefined
        ? 'sm:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)_auto]'
        : 'sm:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)_minmax(0,1fr)_auto]',
    )}>
      <div className="min-w-0">
        <Input
          value={businessName}
          disabled={disabled}
          placeholder={translate("Tên nghiệp vụ")}
          className="h-8 text-xs"
          onChange={(event) => onChange({ business_name: event.target.value })}
        />
        <AiSuggestion
          suggestion={aiBusinessName}
          current={businessName}
          disabled={disabled}
          onAccept={() => onChange({ business_name: aiBusinessName || '' })}
        />
      </div>
      <Input
        value={description}
        disabled={disabled}
        placeholder={translate("Mô tả nghiệp vụ")}
        className="h-8 text-xs"
        onChange={(event) => onChange({ description: event.target.value })}
      />
      {allowedValues !== undefined && (
        <Input
          value={allowedValues}
          disabled={disabled}
          aria-label={translate("Giá trị cho phép (JSON array)")}
          placeholder='["completed", "cancelled"]'
          className="h-8 font-mono text-xs"
          onChange={(event) => onChange({ allowed_values: event.target.value })}
        />
      )}
      <Button
        size="sm"
        variant="outline"
        disabled={disabled || saving || !dirty}
        onClick={onSave}
        className="h-8 shrink-0 gap-1.5 text-[11px]"
      >
        {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
        <Translated text={"Lưu"} />
      </Button>
    </div>
  );
}

function parseAllowedValues(value: string): (string | number | boolean)[] | null {
  const parsed: unknown = JSON.parse(value);
  if (parsed === null) return null;
  if (
    !Array.isArray(parsed) ||
    parsed.some((item) => !['string', 'number', 'boolean'].includes(typeof item))
  ) {
    throw new Error('Giá trị cho phép phải là mảng JSON gồm string, number, boolean hoặc null ở cấp cao nhất.');
  }
  return parsed;
}

/** A row counts as empty when the AI has nothing to show for it yet. */
function cellIsEmpty(draft: Draft | undefined, physicalName: string): boolean {
  return (draft?.description ?? '') === '' && (!draft?.business_name || draft.business_name === physicalName);
}

/** Placeholder shown in place of empty editors while AI enrichment is filling them. */
function SkeletonCell() {
  return <div className="h-8 animate-pulse rounded bg-muted" aria-hidden="true" />;
}

interface TableReviewCardProps {
  dbId: number;
  table: SchemaReviewTable;
  review: SchemaReview;
  drafts: DraftMap;
  expanded: Record<string, boolean>;
  setExpanded: React.Dispatch<React.SetStateAction<Record<string, boolean>>>;
  savingKey: string | null;
  approving: string | null;
  canManageSchema: boolean;
  canApproveSchema: boolean;
  enriching: boolean;
  isDirty: (key: string) => boolean;
  patch: (key: string, value: Partial<Draft>) => void;
  saveRow: (key: string, save: (draft: Draft) => Promise<unknown>) => Promise<void>;
  approve: (tableIds?: number[]) => Promise<void>;
}

/** One collapsible table card with its inline editors and per-table approve action. */
export function TableReviewCard({
  dbId,
  table,
  review,
  drafts,
  expanded,
  setExpanded,
  savingKey,
  approving,
  canManageSchema,
  canApproveSchema,
  enriching,
  isDirty,
  patch,
  saveRow,
  approve,
}: TableReviewCardProps) {
  const key = tableKey(table);
  const open = expanded[key] ?? table.review_status === 'pending_review';
  const pendingColumns = table.columns.filter((c) => c.review_status === 'pending_review').length;
  const duplicateName =
    review.tables.filter((item) => item.table_name === table.table_name).length > 1 && table.physical_schema;
  const tableEmpty = enriching && cellIsEmpty(drafts[key], table.table_name);

  return (
    <section className="shrink-0 rounded-xl border border-border bg-card p-4 shadow-sm">
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => setExpanded((current) => ({ ...current, [key]: !open }))}
          className="flex min-w-0 items-center gap-2 text-left"
          aria-expanded={open}
        >
          <ChevronRight className={cn('h-4 w-4 shrink-0 transition-transform', open && 'rotate-90')} />
          <span className="truncate font-mono text-[13px] text-foreground">
            {duplicateName ? `${table.physical_schema}.${table.table_name}` : table.table_name}
          </span>
        </button>
        <ReviewBadge status={table.review_status} />
        {pendingColumns > 0 && (
          <span className="font-mono text-[10px] text-muted-foreground">
            {pendingColumns}/{table.columns.length} <Translated text={"cột chờ"} /></span>
        )}
        {table.reviewed_at && (
          <span className="font-mono text-[10px] text-muted-foreground">
            <Translated text={"Duyệt lúc"} after />{new Date(table.reviewed_at).toLocaleString()}
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            className="h-8 gap-1.5 text-[11px]"
            disabled={
              !canApproveSchema ||
              approving !== null ||
              (table.review_status === 'approved' && pendingColumns === 0)
            }
            onClick={() => approve([table.table_id])}
          >
            {approving === String(table.table_id) ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <CheckCircle2 className="h-3 w-3" />
            )}
            <Translated text={"Duyệt bảng này"} />
          </Button>
        </div>
      </div>

      <div className="mt-3 flex items-start gap-3">
        {tableEmpty ? (
          <SkeletonCell />
        ) : (
          <RowEditor
            businessName={drafts[key]?.business_name ?? ''}
            description={drafts[key]?.description ?? ''}
            aiBusinessName={table.ai_business_name}
            disabled={!canManageSchema}
            saving={savingKey === key}
            dirty={isDirty(key)}
            onChange={(value) => patch(key, value)}
            onSave={() =>
              saveRow(key, (draft) =>
                updateTableReviewApi(
                  String(dbId),
                  table.table_name,
                  draft.business_name,
                  draft.description,
                  table.table_id,
                ),
              )
            }
          />
        )}
      </div>

      {open && (
        <div className="mt-4 space-y-3 border-t border-border pt-3">
          {table.columns.map((column) => {
            const colKey = columnKey(table, column);
            return (
              <div key={column.column_name} className="flex flex-col gap-1.5">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="truncate font-mono text-[11px] text-muted-foreground">
                    {column.column_name}
                    <span className="ml-1.5 opacity-60">{column.data_type}</span>
                  </span>
                  {column.is_primary_key && (
                    <span className="rounded bg-secondary px-1.5 font-mono text-[9px] text-secondary-foreground">
                      PK
                    </span>
                  )}
                  <ReviewBadge status={column.review_status} />
                </div>
                {enriching && cellIsEmpty(drafts[colKey], column.column_name) ? (
                  <SkeletonCell />
                ) : (
                  <RowEditor
                    businessName={drafts[colKey]?.business_name ?? ''}
                    description={drafts[colKey]?.description ?? ''}
                    allowedValues={drafts[colKey]?.allowed_values ?? 'null'}
                    aiBusinessName={column.ai_business_name}
                    disabled={!canManageSchema}
                    saving={savingKey === colKey}
                    dirty={isDirty(colKey)}
                    onChange={(value) => patch(colKey, value)}
                    onSave={() =>
                      saveRow(colKey, (draft) =>
                        updateColumnReviewApi(
                          String(dbId),
                          table.table_name,
                          column.column_name,
                          draft.business_name,
                          draft.description,
                          table.table_id,
                          parseAllowedValues(draft.allowed_values ?? 'null'),
                        ),
                      )
                    }
                  />
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
