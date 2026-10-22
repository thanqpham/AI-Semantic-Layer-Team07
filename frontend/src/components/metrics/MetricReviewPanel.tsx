'use client';

import type { MetricDefinition, MetricReview } from '@/lib/api';

const LABELS: Record<MetricReview['status'], string> = {
  pass: 'AI đã thẩm định — chờ người duyệt',
  needs_revision: 'Cần sửa trước khi gửi duyệt',
  needs_clarification: 'Cần xác nhận nghiệp vụ',
  unsupported: 'Compiler chưa hỗ trợ KPI này',
  rejected: 'Chưa phù hợp hoặc thiếu dữ liệu',
  error: 'Thẩm định chưa hoàn tất',
};

export function MetricReviewPanel({ review, definition }: { review: MetricReview; definition?: MetricDefinition | null }) {
  return <details className="my-2 rounded-md border border-border bg-secondary/20 p-3 text-xs">
    <summary className="cursor-pointer font-semibold">{LABELS[review.status]}</summary>
    <p className="mt-2 whitespace-pre-wrap">{review.summary}</p>
    {review.requirement && <div className="mt-2"><strong>Yêu cầu đã đối chiếu</strong><p className="whitespace-pre-wrap break-words">{review.requirement}</p></div>}
    {review.issues.map((issue, index) => <div key={index} className="mt-2 space-y-1">
      <p className="font-medium">{issue.message}</p><p>Bằng chứng: {issue.evidence}</p><p>Cần làm: {issue.action}</p>
    </div>)}
    {review.clarification && <p className="mt-2 font-medium">{review.clarification}</p>}
    {review.sources.length > 0 && <ul className="mt-2 list-disc pl-4">{review.sources.map(source => <li key={source.id}>
      <a className="text-primary underline" href={source.url} target="_blank" rel="noopener noreferrer">{source.title}</a>
      <span className="text-muted-foreground"> · Kiểm tra nguồn: {source.reviewed_at}</span>
    </li>)}</ul>}
    {review.revised && <div className="mt-2">
      <p>Đã dùng {review.repair_count}/1 lượt sửa.</p>
      {review.repair_reason && <p>Lý do sửa: {review.repair_reason}</p>}
      {review.repair_feedback?.map((issue, index) => <p key={index}>{issue.message} · {issue.evidence} · {issue.action}</p>)}
    </div>}
    {review.original_definition && <details className="mt-2">
      <summary className="cursor-pointer">Định nghĩa trước và sau thẩm định</summary>
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        <pre aria-label="Định nghĩa ban đầu" className="overflow-auto whitespace-pre-wrap break-all">{JSON.stringify(review.original_definition, null, 2)}</pre>
        <pre aria-label="Định nghĩa cuối" className="overflow-auto whitespace-pre-wrap break-all">{definition ? JSON.stringify(definition, null, 2) : 'Chưa có định nghĩa được chấp nhận.'}</pre>
      </div>
    </details>}
  </details>;
}
