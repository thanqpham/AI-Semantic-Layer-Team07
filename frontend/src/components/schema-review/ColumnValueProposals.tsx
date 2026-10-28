'use client';

import { useCallback, useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import {
  getColumnValueProposalsApi,
  reviewColumnValueProposalsApi,
  scanColumnValueProposalsApi,
  setColumnValueDiscoveryApi,
  type ColumnValueProposal,
} from '@/lib/api';

interface Props {
  dbId: string;
  canManage: boolean;
  canApprove: boolean;
  onReviewChanged?: () => void;
}

function columnLabel(item: ColumnValueProposal): string {
  return [item.physical_schema, item.table_name, item.column_name].filter(Boolean).join('.');
}

/** Review screened categorical values without treating observations as a complete domain. */
export function ColumnValueProposals({ dbId, canManage, canApprove, onReviewChanged }: Props) {
  const [items, setItems] = useState<ColumnValueProposal[]>([]);
  const [enabled, setEnabled] = useState(false);
  const [available, setAvailable] = useState(false);
  const [selected, setSelected] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await getColumnValueProposalsApi(dbId);
      setItems(response.items);
      setEnabled(response.enabled);
      setAvailable(response.available);
      setSelected([]);
      setError('');
    } catch {
      setItems([]);
      setSelected([]);
      setEnabled(false);
      setAvailable(false);
      setError('Không thể tải đề xuất giá trị. Vui lòng thử lại.');
    } finally {
      setLoading(false);
    }
  }, [dbId]);

  useEffect(() => { void load(); }, [load]);

  const scan = async () => {
    setBusy(true);
    setError('');
    try {
      await scanColumnValueProposalsApi(dbId);
      setMessage('Đã yêu cầu quét. Làm mới danh sách sau khi quá trình hoàn tất.');
      await load();
    } catch {
      setError('Không thể bắt đầu quét. Kiểm tra cấu hình và quyền truy cập.');
    } finally {
      setBusy(false);
    }
  };

  const toggleDiscovery = async () => {
    setBusy(true);
    setError('');
    try {
      const result = await setColumnValueDiscoveryApi(dbId, !enabled);
      setEnabled(result.enabled);
      setMessage(result.enabled ? 'Đã bật khám phá giá trị cho kết nối này.' : 'Đã tắt khám phá giá trị cho kết nối này.');
    } catch {
      setError('Không thể thay đổi cấu hình khám phá giá trị.');
    } finally {
      setBusy(false);
    }
  };

  const review = async (action: 'approve' | 'dismiss') => {
    setBusy(true);
    setError('');
    try {
      const result = await reviewColumnValueProposalsApi(dbId, selected, action);
      setMessage(`Đã xử lý ${result.updated} đề xuất.`);
      await load();
      onReviewChanged?.();
    } catch {
      setError('Không thể xử lý đề xuất. Hãy làm mới và thử lại.');
    } finally {
      setBusy(false);
    }
  };

  const pendingIds = items.filter((item) => item.status === 'pending' || item.status === 'pending_review')
    .map((item) => item.id);

  return (
    <section aria-label="Đề xuất giá trị phân loại" className="space-y-4 rounded-xl border border-border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">Đề xuất giá trị phân loại</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Giá trị quan sát từ dữ liệu có thể chưa đầy đủ. Kiểm tra trước khi xác nhận.
          </p>
          {!available && <p className="mt-1 text-xs text-muted-foreground">
            Chức năng chưa khả dụng cho kết nối hoặc chưa được bật trong cấu hình hệ thống.
          </p>}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" onClick={() => void toggleDiscovery()} disabled={!canManage || !available || busy || loading}>
            {enabled ? 'Tắt khám phá tự động' : 'Bật khám phá tự động'}
          </Button>
          <Button size="sm" variant="outline" onClick={() => void load()} disabled={loading || busy}>Làm mới</Button>
          <Button size="sm" variant="outline" onClick={() => void scan()} disabled={!canManage || !available || !enabled || busy || loading}>
            Quét lại
          </Button>
        </div>
      </div>
      {message && <p role="status" className="text-xs text-muted-foreground">{message}</p>}
      {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
      {loading ? <p role="status" className="text-xs">Đang tải đề xuất…</p> : items.length === 0 ? (
        <p className="text-xs text-muted-foreground">Chưa có đề xuất giá trị.</p>
      ) : (
        <>
        <label className="flex items-center gap-2 text-xs">
          <input type="checkbox" checked={pendingIds.length > 0 && selected.length === pendingIds.length}
            disabled={!canApprove || busy || pendingIds.length === 0}
            onChange={(event) => setSelected(event.target.checked ? pendingIds : [])} />
          Chọn tất cả đề xuất đang chờ
        </label>
        <ul className="divide-y divide-border">
          {items.map((item) => {
            const label = columnLabel(item);
            const pending = item.status === 'pending' || item.status === 'pending_review';
            const values = pending || item.status === 'approved' ? item.values : null;
            return (
              <li key={item.id} className="flex items-start gap-3 py-3">
                <input
                  type="checkbox"
                  aria-label={`Chọn ${label}`}
                  checked={selected.includes(item.id)}
                  disabled={!canApprove || busy || !pending}
                  onChange={(event) => setSelected((current) => event.target.checked
                    ? [...current, item.id] : current.filter((id) => id !== item.id))}
                />
                <div className="min-w-0 flex-1 text-xs">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="break-all font-mono font-semibold">{label}</span>
                    <span className="rounded bg-secondary px-1.5 py-0.5">
                      {item.source === 'declared' ? 'Khai báo trong schema' : 'Quan sát từ dữ liệu'}
                    </span>
                    <span className="text-muted-foreground">{pending ? 'Chờ xác nhận' : item.status}</span>
                  </div>
                  {values && <p className="mt-1 break-words">{values.map(String).join(', ')}</p>}
                </div>
              </li>
            );
          })}
        </ul>
        </>
      )}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" onClick={() => void review('approve')} disabled={!canApprove || busy || selected.length === 0}>
          Xác nhận giá trị ({selected.length})
        </Button>
        <Button size="sm" variant="outline" onClick={() => void review('dismiss')} disabled={!canApprove || busy || selected.length === 0}>
          Bỏ qua ({selected.length})
        </Button>
      </div>
    </section>
  );
}
