'use client';

import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Database, Sparkles } from 'lucide-react';
import { getDatabaseOverviewApi, saveDatabaseOverviewApi, generateDatabaseOverviewApi, type DatabaseOverview as Overview } from '@/lib/api';
import { cn } from '@/lib/utils';

/** Review counts shown on the overview panel, derived from the loaded review queue. */
export interface OverviewStats {
  tables: number;
  columns: number;
  pendingTables: number;
  pendingColumns: number;
  pendingValues: number;
  pendingRelationships: number;
}

interface DatabaseOverviewProps {
  dbId: string;
  canManage: boolean;
  canApprove: boolean;
  refreshKey?: number;
  title?: string;
  subtitle?: string;
  stats?: OverviewStats;
  hidden?: boolean;
  onDescribedChange?: (described: boolean) => void;
}

export function DatabaseOverview({ dbId, canManage, canApprove, refreshKey, title, subtitle, stats, hidden, onDescribedChange }: DatabaseOverviewProps) {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const draftRef = useRef('');
  const updateDraft = (value: string) => { draftRef.current = value; setDraft(value); };
  const [error, setError] = useState('');
  const accept = (data: Overview, nextDraft: string) => { setOverview(data); updateDraft(nextDraft); onDescribedChange?.(Boolean(data.description)); };
  useEffect(() => {
    let active = true;
    getDatabaseOverviewApi(dbId).then(data => { if (active) accept(data, data.description || data.draft_description || ''); }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dbId]);
  // Reload after enrichment only when no local edits could be lost.
  useEffect(() => {
    if (!refreshKey || !overview || draft !== (overview.description || overview.draft_description || '')) return;
    const originalDraft = draft;
    getDatabaseOverviewApi(dbId).then(data => { if (draftRef.current === originalDraft) accept(data, data.description || data.draft_description || ''); }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);
  const run = async (action: () => Promise<Overview>) => {
    setBusy(true); setError('');
    try { const result = await action(); accept(result, result.draft_description || result.description || ''); }
    catch (e) { setError(e instanceof Error ? e.message : 'Không thể cập nhật mô tả'); }
    finally { setBusy(false); }
  };
  const dirty = draft !== (overview?.description || '');
  const generate = () => {
    if (!overview) return;
    if (draft && !window.confirm('Tạo lại sẽ thay thế nội dung đang chỉnh sửa. Tiếp tục?')) return;
    void run(async () => { const result = await generateDatabaseOverviewApi(dbId, overview.revision); return { ...result, description: overview.description, draft_description: result.draft_description }; });
  };
  return <section hidden={hidden} aria-label="Tổng quan database" className="min-w-0 space-y-4 rounded-xl border border-border bg-card p-4 shadow-sm">
    <OverviewHeader title={title} subtitle={subtitle} described={Boolean(overview?.description)} />
    {stats && <StatsPanel stats={stats} />}
    <div>
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2"><label className="text-sm font-semibold" htmlFor="database-overview-draft">Mô tả database</label><span className="text-xs text-muted-foreground">{draft.length}/2000 ký tự</span></div>
      <textarea id="database-overview-draft" className="min-h-48 w-full resize-y [field-sizing:content] rounded-lg border border-input bg-background px-4 py-3 text-sm leading-relaxed outline-none transition focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60" rows={4} maxLength={2000} value={draft} onChange={e => updateDraft(e.target.value)} disabled={!canApprove || busy || !overview} placeholder="Tạo mô tả bằng AI hoặc nhập thông tin nghiệp vụ của database." />
      <p className="mt-1.5 text-xs text-muted-foreground">Mô tả sau khi lưu được dùng làm ngữ cảnh cho Metric AI.</p>
    </div>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <div className="flex flex-wrap items-center justify-between gap-3">
      <Button size="sm" variant="outline" disabled={!canManage || busy || !overview} onClick={generate} className="gap-2"><Sparkles className="h-4 w-4" aria-hidden="true" />{busy ? 'Đang xử lý…' : 'Tạo lại bằng AI'}</Button>
      <Button size="sm" disabled={!canApprove || busy || !overview || !dirty || !draft.trim()} onClick={() => overview && void run(() => saveDatabaseOverviewApi(dbId, draft.trim(), overview.revision))}>Lưu mô tả</Button>
    </div>
  </section>;
}

function OverviewHeader({ title, subtitle, described }: { title?: string; subtitle?: string; described: boolean }) {
  return <div className="flex flex-wrap items-center gap-3">
    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary"><Database className="h-4 w-4" aria-hidden="true" /></span>
    <div className="min-w-0">
      <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">Tổng quan database</p>
      <h2 className="truncate text-sm font-semibold">{title || 'Database'}</h2>
      {subtitle && <p className="font-mono text-[11px] text-muted-foreground">{subtitle}</p>}
    </div>
    <span className={cn('ml-auto rounded-full border px-2.5 py-0.5 text-xs font-medium', described
      ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400'
      : 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-400')}>
      {described ? 'Mô tả đã duyệt' : 'Chưa có mô tả'}
    </span>
  </div>;
}

function StatsPanel({ stats }: { stats: OverviewStats }) {
  const total = stats.tables + stats.columns;
  const done = total ? Math.round(((total - stats.pendingTables - stats.pendingColumns) / total) * 100) : 100;
  const items: [string, number][] = [
    ['Bảng chờ', stats.pendingTables], ['Cột chờ', stats.pendingColumns],
    ['Giá trị chờ', stats.pendingValues], ['Liên kết chờ', stats.pendingRelationships],
  ];
  return <div className="space-y-3">
    <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-4">
      {items.map(([label, value]) => <div key={label} className="bg-card px-3 py-2">
        <dt className="text-[11px] text-muted-foreground">{label}</dt>
        <dd className={cn('text-lg font-semibold tabular-nums', value > 0 ? 'text-amber-700 dark:text-amber-300' : 'text-foreground')}>{value}</dd>
      </div>)}
    </dl>
    <div className="flex items-center gap-3 text-xs text-muted-foreground">
      <span className="shrink-0">Tiến độ duyệt</span>
      <div role="progressbar" aria-label="Tiến độ duyệt" aria-valuenow={done} aria-valuemin={0} aria-valuemax={100} className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full bg-emerald-500" style={{ width: `${done}%` }} />
      </div>
      <span className="shrink-0 tabular-nums">{done}% · {stats.tables} bảng · {stats.columns} cột</span>
    </div>
  </div>;
}
