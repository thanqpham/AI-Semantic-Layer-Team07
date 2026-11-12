'use client';

import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Database, Sparkles } from 'lucide-react';
import { getDatabaseOverviewApi, saveDatabaseOverviewApi, generateDatabaseOverviewApi, type DatabaseOverview as Overview } from '@/lib/api';

export function DatabaseOverview({ dbId, canManage, canApprove, refreshKey }: { dbId: string; canManage: boolean; canApprove: boolean; refreshKey?: number }) {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const draftRef = useRef('');
  const updateDraft = (value: string) => { draftRef.current = value; setDraft(value); };
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    getDatabaseOverviewApi(dbId).then(data => { if (active) { setOverview(data); updateDraft(data.description || data.draft_description || ''); } }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [dbId]);
  // Reload after enrichment only when no local edits could be lost.
  useEffect(() => {
    if (!refreshKey || !overview || draft !== (overview.description || overview.draft_description || '')) return;
    const originalDraft = draft;
    getDatabaseOverviewApi(dbId).then(data => { if (draftRef.current === originalDraft) { setOverview(data); updateDraft(data.description || data.draft_description || ''); } }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);
  const run = async (action: () => Promise<Overview>) => {
    setBusy(true); setError('');
    try { const result = await action(); setOverview(result); updateDraft(result.draft_description || result.description || ''); }
    catch (e) { setError(e instanceof Error ? e.message : 'Không thể cập nhật mô tả'); }
    finally { setBusy(false); }
  };
  const dirty = draft !== (overview?.description || '');
  const generate = () => {
    if (!overview) return;
    if (draft && !window.confirm('Tạo lại sẽ thay thế nội dung đang chỉnh sửa. Tiếp tục?')) return;
    void run(async () => { const result = await generateDatabaseOverviewApi(dbId, overview.revision); return { ...result, description: overview.description, draft_description: result.draft_description }; });
  };
  return <section className="shrink-0 overflow-hidden rounded-xl border border-border bg-card" aria-label="Tổng quan database">
    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-5 py-4 sm:px-6">
      <div className="flex items-start gap-3"><span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary"><Database className="h-4 w-4" aria-hidden="true" /></span><div><h2 className="text-sm font-semibold">Tổng quan database</h2><p className="mt-1 text-xs text-muted-foreground">Mô tả ngữ cảnh nghiệp vụ cho toàn bộ nguồn dữ liệu.</p></div></div>
      <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-xs font-medium text-emerald-700 dark:text-emerald-400">{overview?.description ? 'Đã duyệt' : 'Chưa có mô tả'}</span>
    </div>
    <div className="space-y-5 px-5 py-5 sm:px-6">
      <div><div className="mb-2 flex flex-wrap items-baseline justify-between gap-2"><label className="text-sm font-semibold" htmlFor="database-overview-draft">Mô tả database</label><span className="text-xs text-muted-foreground">{draft.length}/2000 ký tự</span></div>
      <textarea id="database-overview-draft" className="min-h-36 w-full resize-y rounded-lg border border-input bg-background px-4 py-3 text-sm leading-relaxed outline-none transition focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60" rows={5} maxLength={2000} value={draft} onChange={e => updateDraft(e.target.value)} disabled={!canApprove || busy || !overview} placeholder="Tạo mô tả bằng AI hoặc nhập thông tin nghiệp vụ của database." />
      <p className="mt-2 text-xs leading-relaxed text-muted-foreground">Mô tả sau khi lưu được dùng làm ngữ cảnh cho Metric AI.</p></div>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    </div>
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border bg-muted/20 px-5 py-4 sm:px-6">
      <Button size="sm" variant="outline" disabled={!canManage || busy || !overview} onClick={generate} className="gap-2"><Sparkles className="h-4 w-4" aria-hidden="true" />{busy ? 'Đang xử lý…' : 'Tạo lại bằng AI'}</Button>
      <Button size="sm" disabled={!canApprove || busy || !overview || !dirty || !draft.trim()} onClick={() => overview && void run(() => saveDatabaseOverviewApi(dbId, draft.trim(), overview.revision))}>Lưu mô tả</Button>
    </div>
  </section>;
}
