'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { ChevronDown, Download, FileSpreadsheet, Upload } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  getColumnValueMappingsApi, previewValueMappingBatchApi, updateColumnValueMappingsApi,
  type ColumnValueMapping, type SchemaReview,
} from '@/lib/api';

type Pair = Pick<ColumnValueMapping, 'db_value' | 'business_value'>;
type Plan = { columnId: number; label: string; version: string; items: Pair[]; incoming: Pair[]; added: number; kept: number; blocked: boolean };

function planColumn(columnId: number, label: string, existing: ColumnValueMapping[], incoming: Pair[], version: string): Plan {
  const items = existing.map(({ db_value, business_value }) => ({ db_value, business_value }));
  let added = 0; let kept = 0;
  for (const item of incoming) {
    const old = items.find((value) => typeof value.db_value === typeof item.db_value && value.db_value === item.db_value);
    if (!old) { items.push(item); added++; }
    else if (!old.business_value.trim()) { old.business_value = item.business_value; added++; }
    else if (old.business_value !== item.business_value) kept++;
  }
  return { columnId, label, version, items, incoming, added, kept, blocked: existing.some((item) => item.status === 'dismissed') || items.length > 100 };
}

/** Preview and save file mappings for several columns without overwriting existing meanings. */
export function ValueMappingBatchImport({ dbId, review, canManage, onReviewChanged }: {
  dbId: string; review: SchemaReview; canManage: boolean; onReviewChanged?: () => void;
}) {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState(false);
  const panelId = useId();
  const fileInput = useRef<HTMLInputElement>(null);
  const container = useRef<HTMLElement>(null);
  const toggleButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!expanded) return;
    const dismiss = (event: PointerEvent) => {
      if (!container.current?.contains(event.target as Node)) setExpanded(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setExpanded(false); toggleButton.current?.focus(); }
    };
    document.addEventListener('pointerdown', dismiss);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', dismiss);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [expanded]);

  const preview = async (file: File) => {
    const fileType = file.name.split('.').pop()?.toLowerCase();
    setExpanded(true);
    setPlans([]); setError(''); setMessage('');
    if (!['json', 'csv', 'xlsx'].includes(fileType ?? '') || file.size > 2_000_000) {
      setError('Chọn file JSON, CSV hoặc XLSX có dung lượng tối đa 2 MB.'); return;
    }
    setBusy(true);
    try {
      const result = await previewValueMappingBatchApi(dbId, file, fileType as 'json' | 'csv' | 'xlsx');
      const labels = new Map(review.tables.flatMap((table) => table.columns.map((column) =>
        [column.column_id, [table.physical_schema, table.table_name, column.column_name].filter(Boolean).join('.')] as const)));
      const next = await Promise.all(result.columns.map(async ({ column_id, items }) => {
        const current = await getColumnValueMappingsApi(dbId, column_id);
        return planColumn(column_id, labels.get(column_id) ?? `Cột ${column_id}`, current.items, items, current.version);
      }));
      setPlans(next);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Không thể đọc file giá trị.');
    } finally { setBusy(false); }
  };

  const save = async () => {
    const selected = plans.filter((plan) => plan.added > 0 && !plan.blocked);
    let saved = 0;
    setBusy(true); setError(''); setMessage('');
    try {
      for (const plan of selected) {
        await updateColumnValueMappingsApi(dbId, plan.columnId, plan.items, false, plan.version);
        saved++;
      }
      setPlans([]);
      setMessage(`Đã lưu ${saved} cột; giá trị mới hoặc thay đổi đang chờ duyệt. Tải lại giá trị tại cột đang mở để xem cập nhật.`);
    } catch (caught) {
      setPlans([]);
      setError(`Đã lưu ${saved}/${selected.length} cột. Dừng do lỗi hoặc xung đột; tải lại file để tiếp tục. ${caught instanceof Error ? caught.message : ''}`);
    } finally {
      setBusy(false);
      if (saved) onReviewChanged?.();
    }
  };

  return <section ref={container} className="relative shrink-0 text-xs" aria-label="Nạp giá trị từ file">
    <div className="flex justify-end">
      <Button type="button" variant="outline" size="sm" className="rounded-r-none border-r-0"
        disabled={!canManage || busy} onClick={() => fileInput.current?.click()}>
        <Upload aria-hidden="true" /> Nạp giá trị nghiệp vụ
      </Button>
      <Button ref={toggleButton} type="button" variant="outline" size="icon-sm" className="rounded-l-none"
        aria-label="Chi tiết nạp giá trị nghiệp vụ" aria-expanded={expanded} aria-controls={panelId}
        onClick={() => setExpanded(!expanded)}>
        <ChevronDown className={expanded ? 'rotate-180' : ''} aria-hidden="true" />
      </Button>
      <input ref={fileInput} aria-label="Nạp file cho nhiều cột" type="file" accept=".json,.csv,.xlsx" disabled={!canManage || busy}
        className="sr-only" tabIndex={-1} onChange={(event) => {
          const file = event.target.files?.[0]; event.target.value = ''; if (file) void preview(file);
        }} />
    </div>
    <div id={panelId} hidden={!expanded} className="absolute right-0 top-full z-50 mt-2 max-h-[calc(100vh-8rem)] w-[min(36rem,calc(100vw-3rem))] space-y-3 overflow-y-auto rounded-xl border border-border bg-card p-4 shadow-xl">
    <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-4">
      <div className="flex min-w-0 items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-secondary text-muted-foreground">
          <FileSpreadsheet className="h-4 w-4" aria-hidden="true" />
        </span>
        <div className="min-w-0 space-y-1">
          <p className="text-sm font-medium text-foreground">Nạp giá trị cho nhiều cột</p>
          <p className="text-muted-foreground">Thêm danh mục giá trị và ý nghĩa nghiệp vụ từ file.</p>
          <p className="text-[11px] text-muted-foreground">JSON, CSV, Excel <span aria-hidden="true">·</span> Tối đa 2 MB</p>
        </div>
      </div>
      <div className="ml-auto flex shrink-0 items-center gap-2">
        <a download="value-mappings-multi-column.csv" href="data:text/csv;charset=utf-8,column_id%2Cdb_value%2Cbusiness_value%0A21%2Cpending%2CCho%20xu%20ly%0A" className="inline-flex h-8 items-center gap-1.5 rounded-md px-2 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <Download className="h-3.5 w-3.5" aria-hidden="true" /> Tải mẫu CSV
        </a>
      </div>
    </div>
    <details className="group border-t border-border/70 pt-2.5 text-muted-foreground">
      <summary className="inline-flex cursor-pointer items-center gap-1.5 hover:text-foreground">
        <ChevronDown className="h-3.5 w-3.5 transition-transform group-open:rotate-180" aria-hidden="true" /> Hướng dẫn định dạng file
      </summary>
      <p className="mt-2 leading-relaxed">CSV hoặc Excel cần các cột <code>column_id</code>, <code>db_value</code>, <code>business_value</code>. File Excel sử dụng sheet đầu tiên; JSON có thể chứa nhiều cột.</p>
    </details>
    {busy && <p role="status">Đang xử lý file…</p>}
    {error && <p role="alert" className="text-destructive">{error}</p>}
    {message && <p role="status">{message}</p>}
    {plans.length > 0 && <div className="space-y-2">
      <p className="font-medium">Xem trước {plans.length} cột</p>
      <ul className="max-h-48 space-y-1 overflow-auto">{plans.map((plan) => <li key={plan.columnId}>
        {plan.label}: {plan.added} giá trị mới hoặc bổ sung nghĩa, {plan.kept} giá trị giữ nguyên
        {plan.blocked && ' — bỏ qua: có giá trị đã bỏ qua hoặc vượt 100 giá trị'}
        <details><summary className="cursor-pointer">Xem giá trị trong file</summary><ul className="pl-4">
          {plan.incoming.map((item, index) => {
            const saved = plan.items.find((value) => typeof value.db_value === typeof item.db_value && value.db_value === item.db_value);
            return <li key={index}>{String(item.db_value)} → {item.business_value}
              {saved && saved.business_value !== item.business_value && ` (giữ nguyên: ${saved.business_value})`}</li>;
          })}
        </ul></details>
      </li>)}</ul>
      <p className="text-muted-foreground">Lưu lần lượt từng cột; các giá trị được thêm hoặc sửa cần phê duyệt. Ý nghĩa đã có được giữ nguyên.</p>
      <Button size="sm" disabled={busy || !canManage || !plans.some((plan) => plan.added > 0 && !plan.blocked)} onClick={() => void save()}>Lưu các giá trị chờ duyệt</Button>
    </div>}
    </div>
  </section>;
}
