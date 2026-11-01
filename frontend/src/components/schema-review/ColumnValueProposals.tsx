'use client';

import { useState } from 'react';
import { ChevronRight, RefreshCw } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  getColumnValueMappingsApi,
  reviewColumnValueMappingsApi,
  type ColumnValueMapping,
} from '@/lib/api';

type ValueType = 'string' | 'number' | 'boolean';
type Row = { value: string; type: ValueType; business: string; source: ColumnValueMapping['source']; status: ColumnValueMapping['status'] };
type Values = { rows: Row[]; complete: boolean };
type Props = { dbId: string; columnId: number; columnName: string; canManage: boolean; canApprove: boolean; onReviewChanged?: () => void };

function toDraft(items: ColumnValueMapping[], complete: boolean): Values {
  return { rows: items.map((item) => ({ value: String(item.db_value), type: typeof item.db_value as ValueType,
    business: item.business_value, source: item.source, status: item.status })), complete };
}

function toPayload(rows: Row[]): Pick<ColumnValueMapping, 'db_value' | 'business_value'>[] {
  return rows.map((row) => ({ db_value: row.type === 'number' ? Number(row.value) : row.type === 'boolean'
    ? row.value === 'true' : row.value, business_value: row.business }));
}

function validate(rows: Row[], baseline: Row[]): string | null {
  for (const [index, row] of rows.entries()) {
    const unchangedLegacy = row.source === 'legacy' && baseline.some((old) =>
      old.source === 'legacy' && old.value === row.value && old.type === row.type && old.business === row.business);
    if (!row.business.trim() && !unchangedLegacy) return `Dòng ${index + 1}: nhập ý nghĩa nghiệp vụ.`;
    if (row.type === 'number' && (!row.value.trim() || !Number.isFinite(Number(row.value)))) return `Dòng ${index + 1}: nhập số hợp lệ.`;
    if (row.type === 'boolean' && !['true', 'false'].includes(row.value)) return `Dòng ${index + 1}: nhập true hoặc false.`;
  }
  const keys = toPayload(rows).map((row) => `${typeof row.db_value}:${String(row.db_value)}`);
  return new Set(keys).size === keys.length ? null : 'Giá trị DB bị trùng; hãy sửa hoặc xóa dòng trùng.';
}

function errorMessage(caught: unknown, fallback: string): string {
  if (typeof caught === 'object' && caught !== null && 'status' in caught && caught.status === 409) {
    return 'Giá trị đã thay đổi ở phiên khác. Bản nháp vẫn được giữ; hãy tải lại trước khi lưu hoặc duyệt.';
  }
  return caught instanceof Error ? caught.message : fallback;
}

/** Edit value meanings in the context of a single semantic column. */
export function ColumnValueEditor({ dbId, columnId, columnName, canManage, canApprove, onReviewChanged }: Props) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<Values | null>(null);
  const [baseline, setBaseline] = useState<Values | null>(null);
  const [version, setVersion] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [scope, setScope] = useState<boolean | null>(null);
  const dirty = JSON.stringify(draft) !== JSON.stringify(baseline);
  const pending = baseline?.rows.filter((row) => row.status === 'pending') ?? [];
  const approvedCount = baseline?.rows.filter((row) => row.status === 'approved').length ?? 0;
  const panelId = `column-values-${columnId}`;

  const load = async () => {
    setBusy(true); setError('');
    try {
      const result = await getColumnValueMappingsApi(dbId, columnId);
      const next = toDraft(result.items, result.complete);
      setDraft(next); setBaseline(next); setVersion(result.version); setScope(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Không thể tải giá trị.');
    } finally { setBusy(false); }
  };

  const approve = async () => {
    if (!draft || scope === null || !draft.rows.length) return;
    const problem = validate(draft.rows, baseline?.rows ?? []);
    if (problem) { setError(problem); return; }
    setBusy(true); setError(''); setMessage('');
    try {
      await reviewColumnValueMappingsApi(dbId, columnId, [], 'approve', version,
        { items: toPayload(draft.rows), complete: scope });
      await load(); setMessage('Đã duyệt giá trị và phạm vi danh sách.'); onReviewChanged?.();
    } catch (caught) {
      setError(errorMessage(caught, 'Không thể duyệt giá trị.'));
    } finally { setBusy(false); }
  };

  const changeRow = (index: number, update: Partial<Row>) => {
    if (!draft) return;
    setDraft({ rows: draft.rows.map((row, i) => i === index ? { ...row, ...update } : row), complete: false });
  };

  return <section className="mt-1 rounded-lg border border-border bg-background/50 p-2">
    <div className="flex items-center justify-between gap-2">
    <button type="button" aria-expanded={open} aria-controls={panelId} className="flex items-center gap-1 text-left text-xs font-medium"
      onClick={() => { setOpen(!open); if (!open && !draft && !busy) void load(); }}>
      <ChevronRight className={`h-3.5 w-3.5 ${open ? 'rotate-90' : ''}`} aria-hidden="true" />
      Giá trị nghiệp vụ {baseline && `· ${approvedCount} đã duyệt · ${pending.length} chờ duyệt`}{dirty && ' · Chưa lưu'}
    </button>
    {open && draft && <Button size="icon-sm" variant="outline" aria-label={error ? "Tải lại từ máy chủ" : "Tải lại giá trị"} title={error ? "Tải lại từ máy chủ" : "Tải lại giá trị"} disabled={busy} onClick={() => {
      if (!dirty || window.confirm('Tải lại sẽ bỏ các thay đổi chưa lưu. Tiếp tục?')) void load();
    }}><RefreshCw aria-hidden="true" /></Button>}
    </div>
    <div id={panelId} hidden={!open} className="mt-3 space-y-3">
      {busy && !draft && <p role="status" className="text-xs">Đang tải giá trị…</p>}
      {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
      {message && <p role="status" className="text-xs text-muted-foreground">{message}</p>}
      {!draft && !busy && <Button size="sm" variant="outline" onClick={() => void load()}>Thử tải lại</Button>}
      {draft && <>
        {draft.rows.length === 0 && <p className="text-xs text-muted-foreground">Chưa có giá trị nào cho cột này.</p>}
        {draft.rows.map((row, index) => <div key={index} className="grid gap-2 rounded-md border border-border p-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-end">
          <label className="space-y-1 text-xs"><span>Giá trị trong DB</span>
            <Input aria-label={`Giá trị DB ${index + 1} của ${columnName}`} value={row.value} disabled={!canManage || busy} className="h-8 font-mono text-xs"
              onChange={(event) => changeRow(index, { value: event.target.value })} />
          </label>
          <label className="space-y-1 text-xs"><span>Giá trị nghiệp vụ</span>
            <Input aria-label={`Ý nghĩa nghiệp vụ ${index + 1} của ${columnName}`} value={row.business} disabled={!canManage || busy} className="h-8 text-xs"
              onChange={(event) => changeRow(index, { business: event.target.value })} />
          </label>
          <Button size="sm" variant="ghost" aria-label={`Xóa giá trị ${index + 1} của ${columnName}`} disabled={!canManage || busy}
            onClick={() => setDraft({ rows: draft.rows.filter((_, i) => i !== index), complete: false })}>Xóa</Button>
          <label className="text-xs">Kiểu giá trị{' '}
            <select aria-label={`Kiểu giá trị DB ${index + 1} của ${columnName}`} value={row.type} disabled={!canManage || busy}
              className="rounded border border-border bg-background px-1 py-1" onChange={(event) => changeRow(index, { type: event.target.value as ValueType })}>
              <option value="string">Chuỗi</option><option value="number">Số</option><option value="boolean">Đúng/sai</option>
            </select>
          </label>
          <p className="text-xs text-muted-foreground">{JSON.stringify(row) !== JSON.stringify(baseline?.rows[index]) ? 'Chưa lưu' : row.status === 'approved' ? 'Đã duyệt' : row.status === 'pending' ? 'Chờ duyệt' : 'Đã bỏ qua'} · {row.source === 'legacy' ? 'Giá trị cũ' : row.source === 'declared' ? 'Khai báo schema' : 'Nhập thủ công'}</p>
        </div>)}
        <Button size="sm" variant="outline" disabled={!canManage || busy} onClick={() => setDraft({ rows: [...draft.rows,
          { value: '', type: 'string', business: '', source: 'manual', status: 'pending' }], complete: false })}>+ Thêm giá trị</Button>
        <fieldset className="space-y-1 text-xs"><legend>Phạm vi danh sách</legend>
          <label className="mr-4"><input type="radio" name={`${panelId}-scope`} checked={scope === false} disabled={!canManage || !canApprove || busy} onChange={() => setScope(false)} /> Tham khảo</label>
          <label><input type="radio" name={`${panelId}-scope`} checked={scope === true} disabled={!canManage || !canApprove || busy} onChange={() => setScope(true)} /> Đầy đủ</label>
          <p className="text-muted-foreground">Tham khảo: không loại trừ giá trị khác. Đầy đủ: khai báo toàn bộ giá trị hợp lệ.</p>
        </fieldset>
        <Button size="sm" variant="outline" disabled={!canManage || !canApprove || busy || scope === null || draft.rows.length === 0} onClick={() => void approve()}>Duyệt giá trị</Button>
        {!canApprove && pending.length > 0 && <p className="text-xs text-muted-foreground">Cần người có quyền phê duyệt các giá trị đang chờ.</p>}
      </>}
    </div>
  </section>;
}
