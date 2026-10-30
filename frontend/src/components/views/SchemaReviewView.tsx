'use client';

import { AlertCircle, CheckCircle2, Loader2, Sparkles } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { Button } from '@/components/ui/button';
import {
  approveSchemaReviewApi,
  generateDescriptionsApi,
  getEnrichStatusApi,
  getSchemaReviewApi,
  type EnrichStatus,
  type SchemaReview,
} from '@/lib/api';
import { SectionLabel, type WorkspaceDatabase } from '@/components/workspace/shared';
import { cn } from '@/lib/utils';
import { ViewHeader } from '@/components/workspace/ViewHeader';
import { Translated } from '@/components/ui/translated';
import { EnrichmentProgressBanner } from '@/components/schema-review/EnrichmentProgressBanner';
import { TableReviewCard, columnKey, tableKey, type Draft, type DraftMap } from '@/components/schema-review/TableReviewCard';
import { RelationshipsPanel } from '@/components/schema-review/RelationshipsPanel';
import { ColumnValueProposals } from '@/components/schema-review/ColumnValueProposals';
import { useLanguage } from '@/context/LanguageContext';

interface SchemaReviewViewProps {
  dbId?: number | null;
  database?: WorkspaceDatabase | null;
  canManageSchema?: boolean;
  canApproveSchema?: boolean;
  onNotify?: (message: string) => void;
  onReviewChanged?: () => void;
  onRelationshipDirtyChange?: (dirty: boolean) => void;
}

function buildDrafts(review: SchemaReview): DraftMap {
  const drafts: DraftMap = {};
  for (const table of review.tables) {
    drafts[tableKey(table)] = {
      business_name: table.business_name || '',
      description: table.description || '',
    };
    for (const column of table.columns) {
      drafts[columnKey(table, column)] = {
        business_name: column.business_name || '',
        description: column.description || '',
        allowed_values: JSON.stringify(column.allowed_values ?? null),
      };
    }
  }
  return drafts;
}

export function SchemaReviewView({
  dbId,
  database,
  canManageSchema = false,
  canApproveSchema = false,
  onNotify,
  onReviewChanged,
  onRelationshipDirtyChange,
}: SchemaReviewViewProps) {
  const { translate } = useLanguage();
  const [reviewTab, setReviewTab] = useState<'tables' | 'relationships' | 'values'>('tables');
  const [review, setReview] = useState<SchemaReview | null>(null);
  const [drafts, setDrafts] = useState<DraftMap>({});
  const [baseline, setBaseline] = useState<DraftMap>({});
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [approving, setApproving] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [enrich, setEnrich] = useState<EnrichStatus | null>(null);
  const [pollTick, setPollTick] = useState(0);

  const load = useCallback(async () => {
    if (!dbId || !canManageSchema) return;
    setLoading(true);
    setError('');
    try {
      const data = await getSchemaReviewApi(String(dbId));
      setReview(data);
      const next = buildDrafts(data);
      setDrafts(next);
      setBaseline(next);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Không thể tải hàng đợi review');
    } finally {
      setLoading(false);
    }
  }, [dbId, canManageSchema]);

  useEffect(() => {
    void load();
  }, [load]);

  const isDirty = (key: string) =>
    drafts[key] !== undefined &&
    (drafts[key].business_name !== baseline[key]?.business_name ||
      drafts[key].description !== baseline[key]?.description ||
      drafts[key].allowed_values !== baseline[key]?.allowed_values);

  const patch = (key: string, value: Partial<Draft>) =>
    setDrafts((current) => ({ ...current, [key]: { ...current[key], ...value } }));

  const saveRow = async (key: string, save: (draft: Draft) => Promise<unknown>) => {
    const draft = drafts[key];
    if (!dbId || !draft) return;
    setSavingKey(key);
    setError('');
    try {
      await save(draft);
      setBaseline((current) => ({ ...current, [key]: { ...draft } }));
      onNotify?.('Đã lưu bản chỉnh sửa, chờ phê duyệt');
      await load();
      onReviewChanged?.();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Không thể lưu chỉnh sửa');
    } finally {
      setSavingKey(null);
    }
  };

  const approve = async (tableIds?: number[]) => {
    if (!dbId) return;
    setApproving(tableIds ? String(tableIds[0]) : '*');
    setError('');
    try {
      const result = await approveSchemaReviewApi(String(dbId), undefined, tableIds);
      onNotify?.(
        `Đã duyệt ${result.approved_tables} bảng và ${result.approved_columns} cột vào Metadata Store`,
      );
      await load();
      onReviewChanged?.();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Không thể phê duyệt schema');
    } finally {
      setApproving(null);
    }
  };

  const pendingTotal = (review?.pending_tables || 0) + (review?.pending_columns || 0);
  const dirtyCount = useMemo(
    () => Object.keys(drafts).filter((key) => isDirty(key)).length,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [drafts, baseline],
  );
  const dirtyRef = useRef(dirtyCount);
  useEffect(() => {
    dirtyRef.current = dirtyCount;
  }, [dirtyCount]);

  // Poll fill-missing enrichment progress; refresh the queue as tables complete.
  const completedRef = useRef(-1);
  const statusRef = useRef<EnrichStatus | null>(null);
  const pollEnrich = useCallback(async () => {
    if (!dbId) return;
    try {
      const snapshot = await getEnrichStatusApi(String(dbId));
      statusRef.current = snapshot;
      setEnrich(snapshot);
      if (snapshot.status === 'running' && snapshot.completed_tables > completedRef.current) {
        completedRef.current = snapshot.completed_tables;
        if (dirtyRef.current === 0) void load();
      }
      if (snapshot.status === 'succeeded' || snapshot.status === 'failed') {
        // Reset so a retry run (which counts only still-missing tables) can trigger refetches again.
        completedRef.current = -1;
        if (dirtyRef.current === 0) void load();
      }
      if (snapshot.status === 'succeeded') {
        window.setTimeout(
          () => setEnrich((current) => (current?.status === 'succeeded' ? null : current)),
          4000,
        );
      }
    } catch {
      // Polling is best-effort; the banner keeps its last snapshot.
    }
  }, [dbId, load]);

  useEffect(() => {
    if (!dbId || !canManageSchema) return;
    const immediate = setTimeout(() => void pollEnrich(), 0);
    let stopped = false;
    const id = setInterval(() => {
      if (stopped) return;
      const last = statusRef.current;
      if (last && last.status !== 'running') {
        stopped = true;
        clearInterval(id);
        return;
      }
      void pollEnrich();
    }, 2000);
    return () => {
      clearTimeout(immediate);
      clearInterval(id);
    };
  }, [dbId, canManageSchema, pollEnrich, pollTick]);

  const onGenerate = async () => {
    if (!dbId) return;
    setError('');
    try {
      await generateDescriptionsApi(String(dbId));
      setPollTick((tick) => tick + 1);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Không thể khởi tạo tạo mô tả AI');
    }
  };

  if (dbId && !canManageSchema) {
    return <div className="flex h-full w-full flex-col overflow-hidden">
      <ViewHeader eyebrow="Flow 1 HITL Review" title="Schema Review" description="Review access is restricted to schema managers." />
      <p role="status" className="p-6 text-sm text-muted-foreground"><Translated text="Schema Review requires schema management permission. Contact your Data Lead." /></p>
    </div>;
  }

  const enriching = enrich?.status === 'running';

  return (
    <div className="flex h-full min-h-0 w-full flex-col overflow-hidden bg-background text-foreground">
      <ViewHeader
        eyebrow="Flow 1 · HITL Review"
        title={translate("Schema Review")}
        description="Tên nghiệp vụ do AI đề xuất chỉ được lưu chính thức vào Metadata Store sau khi BA/DA chỉnh sửa và phê duyệt."
        database={database}
        actions={
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={!dbId || enriching}
              onClick={() => void onGenerate()}
              className="gap-2 text-xs"
            >
              <Sparkles className="h-4 w-4" />
              <Translated text={"Tạo mô tả AI"} />
            </Button>
            <Button
              size="sm"
              disabled={!canApproveSchema || pendingTotal === 0 || approving !== null}
              onClick={() => approve()}
              className="gap-2 text-xs"
            >
              {approving === '*' ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <CheckCircle2 className="h-4 w-4" />
              )}
              <Translated text={"Duyệt bảng & cột ("} />{pendingTotal})
            </Button>
          </div>
        }
      />

      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4 sm:p-6">
        {enrich && enrich.status !== 'idle' && (
          <EnrichmentProgressBanner status={enrich} onRetry={() => void onGenerate()} />
        )}
        <div role="tablist" onKeyDown={event => {
          if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
          event.preventDefault();
          const names = ['tables', 'relationships', 'values'] as const;
          const offset = event.key === 'ArrowRight' ? 1 : -1;
          const index = (names.indexOf(reviewTab) + offset + names.length) % names.length;
          setReviewTab(names[index]);
          event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]')[index]?.focus();
        }} aria-label={translate('Loại review')} className="flex flex-wrap gap-2">
          <Button role="tab" id="tables-tab" tabIndex={reviewTab==='tables'?0:-1} aria-selected={reviewTab==='tables'} aria-controls="tables-review" onClick={()=>setReviewTab('tables')} variant={reviewTab==='tables'?'default':'outline'}><Translated text="Bảng & cột" /></Button>
          <Button role="tab" id="relationships-tab" tabIndex={reviewTab==='relationships'?0:-1} aria-selected={reviewTab==='relationships'} aria-controls="relationships-review" onClick={()=>setReviewTab('relationships')} variant={reviewTab==='relationships'?'default':'outline'}>
            <Translated text="Liên kết" />
            {Boolean(review?.pending_relationships) && ` (${review?.pending_relationships})`}
          </Button>
          <Button role="tab" id="values-tab" tabIndex={reviewTab === 'values' ? 0 : -1} aria-selected={reviewTab === 'values'} aria-controls="values-review" onClick={() => setReviewTab('values')} variant={reviewTab === 'values' ? 'default' : 'outline'}>Giá trị đề xuất</Button>
        </div>
        <p className="text-xs text-muted-foreground">
          {review?.pending_relationships
            ? `${review.pending_relationships} liên kết chờ xác nhận riêng; duyệt bảng & cột không duyệt liên kết.`
            : 'Tất cả liên kết đã được phê duyệt; bạn có thể dùng AI đề xuất hoặc thêm liên kết thủ công.'}
        </p>
        {dbId && <div id="relationships-review" role="tabpanel" aria-labelledby="relationships-tab" hidden={reviewTab!=='relationships'} className={cn("min-h-0 flex-1 flex-col", reviewTab==='relationships' ? "flex" : "hidden")}><RelationshipsPanel key={dbId} dbId={String(dbId)} canManageSchema={canManageSchema} canApproveSchema={canApproveSchema} onNotify={onNotify} onDirtyChange={onRelationshipDirtyChange} onReviewChanged={()=>{void load();onReviewChanged?.();}} /></div>}
        <div id="values-review" role="tabpanel" aria-labelledby="values-tab" hidden={reviewTab !== 'values'}>
          {dbId && reviewTab === 'values' && <ColumnValueProposals key={dbId} dbId={String(dbId)} canManage={canManageSchema} canApprove={canApproveSchema} onReviewChanged={() => { void load(); onReviewChanged?.(); }} />}
        </div>
        <div id="tables-review" role="tabpanel" aria-labelledby="tables-tab" hidden={reviewTab!=='tables'} className="space-y-4">
        {error && (
          <p className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-xs text-destructive">
            <AlertCircle className="h-4 w-4 shrink-0" />
            {error}
          </p>
        )}
        {dirtyCount > 0 && (
          <p className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-700 dark:text-amber-300">
            {dirtyCount} <Translated text={"chỉnh sửa chưa được lưu. Nhấn Lưu trên từng dòng trước khi phê duyệt."} /></p>
        )}

        <div className="flex items-center gap-4">
          <SectionLabel>
            {review?.tables.length || 0} <Translated text={"bảng ·"} after />{review?.pending_tables || 0} <Translated text={"bảng chờ ·"} />{' '}
            {review?.pending_columns || 0} <Translated text={"cột chờ"} /></SectionLabel>
          {loading && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
        </div>

        {review?.tables.length === 0 && !loading && (
          <p className="rounded-lg border border-border bg-secondary p-4 text-xs text-muted-foreground">
            <Translated text={"Chưa có metadata nào. Hãy chạy Generate ở AI Studio để tạo Semantic Layer trước."} />
          </p>
        )}

        {review?.tables.map((table) => (
          <TableReviewCard
            key={table.table_id}
            dbId={dbId!}
            table={table}
            review={review}
            drafts={drafts}
            expanded={expanded}
            setExpanded={setExpanded}
            savingKey={savingKey}
            approving={approving}
            canManageSchema={canManageSchema}
            canApproveSchema={canApproveSchema}
            enriching={Boolean(enriching)}
            isDirty={isDirty}
            patch={patch}
            saveRow={saveRow}
            approve={approve}
          />
        ))}
        </div>
      </div>
    </div>
  );
}
