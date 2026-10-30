import type { EnrichStatus } from '@/lib/api';

interface Props {
  status: EnrichStatus;
  onRetry: () => void;
}

/** Progress banner for the fill-missing AI enrichment run; renders null when idle. */
export function EnrichmentProgressBanner({ status, onRetry }: Props) {
  if (status.status === 'idle') return null;

  if (status.status === 'failed') {
    return (
      <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive" role="alert">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span>Tạo mô tả AI thất bại: {status.error ?? 'lỗi không rõ nguyên nhân'}</span>
          <button type="button" onClick={onRetry} className="rounded-md border border-destructive/40 px-3 py-1 font-medium hover:bg-destructive/20">
            Thử lại
          </button>
        </div>
      </div>
    );
  }

  if (status.status === 'succeeded') {
    return (
      <div className="rounded-lg border border-emerald-300 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
        ✅ Đã tạo mô tả xong
      </div>
    );
  }

  const label = status.phase === 'analyzing'
    ? '⚡ Đang phân tích schema…'
    : `⚡ Đang tạo mô tả AI… ${status.completed_tables}/${status.total_tables} bảng`
      + (status.current_table ? ` · đang xử lý: ${status.current_table}` : '');
  const percent = status.total_tables > 0
    ? Math.round((status.completed_tables / status.total_tables) * 100)
    : 0;

  return (
    <div className="rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-3 text-sm text-indigo-700">
      <div className="mb-2" aria-live="polite">{label}</div>
      {status.phase === 'analyzing' ? (
        <div className="h-2 overflow-hidden rounded-full bg-indigo-100">
          <div className="h-full w-1/3 animate-pulse rounded-full bg-indigo-500" />
        </div>
      ) : (
        <div
          role="progressbar"
          aria-valuenow={percent}
          aria-valuemin={0}
          aria-valuemax={100}
          className="h-2 overflow-hidden rounded-full bg-indigo-100"
        >
          <div className="h-full rounded-full bg-indigo-500 transition-all duration-500" style={{ width: `${percent}%` }} />
        </div>
      )}
    </div>
  );
}
