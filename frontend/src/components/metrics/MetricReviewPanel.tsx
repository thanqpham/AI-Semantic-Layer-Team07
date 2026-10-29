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

const ROLES: Record<string, string> = { coordinator: 'Metric Workflow Coordinator', schema_analyst: 'Schema Analyst',
  metric_builder: 'Metric Designer Agent', technical_validator: 'Kiểm tra kỹ thuật', data_lead_reviewer: 'Metric Reviewer Agent' };
const INTENTS: Record<string, string> = { request: 'Giao việc', result: 'Trả kết quả', revision_request: 'Yêu cầu sửa',
  clarification: 'Cần làm rõ', failure: 'Báo lỗi' };
const CRITERIA: Record<string, string> = { tax_basis: 'Cơ sở thuế', refund_policy: 'Hoàn tiền',
  order_status: 'Trạng thái đơn', time_basis: 'Mốc thời gian', population: 'Đối tượng tính',
  numerator: 'Tử số', denominator: 'Mẫu số', formula_basis: 'Cơ sở công thức' };
const VALUES: Record<string, string> = { excludes_tax: 'Trước thuế', includes_vat: 'Gồm VAT',
  subtract_sales_reversals: 'Trừ điều chỉnh giảm', confirmed_completed: 'Đơn hoàn tất đã xác nhận' };
const REASONS: Record<NonNullable<MetricReview['reason_code']>, string> = {
  UNRESOLVED_ASSUMPTION: 'Còn giả định nghiệp vụ chưa xác nhận',
  MISSING_GRAIN: 'Chưa xác định được grain của dữ liệu',
  VARIANT_CONFLICT: 'Biến thể không khớp yêu cầu',
  MISSING_RATIO: 'Thiếu công thức tỷ lệ',
  TECHNICAL_VALIDATION: 'Không đạt kiểm tra kỹ thuật',
  REVIEWER_FINDING: 'Cần xử lý nhận xét thẩm định',
  BUILDER_CLARIFICATION: 'Agent cần thêm thông tin',
  BUILDER_UNSUPPORTED: 'Agent không thể hỗ trợ từ schema hiện có',
  BUILDER_REJECTED: 'Agent không đề xuất metric này',
  INVALID_AGENT_OUTPUT: 'Phản hồi của agent không hợp lệ',
  PROVIDER_FAILURE: 'Không thể hoàn tất lời gọi LLM',
  OTHER: 'Lý do chưa được phân loại',
};

export function MetricReviewPanel({ review, definition }: { review: MetricReview; definition?: MetricDefinition | null }) {
  const error = review.execution_error;
  const heading = error?.code === 'INVALID_AGENT_OUTPUT'
    ? (error.stage === 'reviewer' ? 'AI chưa trả được thẩm định hợp lệ' : 'AI chưa tạo được định nghĩa hợp lệ')
    : error?.code === 'RATE_LIMITED' ? 'Đang bị giới hạn API'
      : error?.code === 'QUOTA_EXHAUSTED' ? 'Tài khoản LLM đã hết quota'
        : error?.code === 'LLM_BUSY' ? 'Tài khoản LLM đang bận'
          : error?.code === 'PROVIDER_ERROR' ? 'Không thể gọi model' : LABELS[review.status];
  return <details className="my-2 rounded-md border border-border bg-secondary/20 p-3 text-xs">
    <summary className="cursor-pointer font-semibold">{heading}</summary>
    <p className="mt-2 whitespace-pre-wrap">{review.summary}</p>
    {review.reason_code && <p className="mt-2"><strong>Nhóm lý do:</strong> {REASONS[review.reason_code]}</p>}
    {error && <p className="mt-2">{error.message}
      {error.retry_after_seconds != null && ` Có thể thử lại sau khoảng ${Math.ceil(error.retry_after_seconds)} giây.`}
    </p>}
    {!!error?.validation_errors?.length && <div className="mt-2">
      <strong>Trường phản hồi không hợp lệ</strong>
      <ul className="mt-1 list-disc pl-4">{error.validation_errors.map((issue, index) =>
        <li key={`${issue.field}-${index}`}><code>{issue.field}</code> · <code>{issue.type}</code>: {issue.message}</li>
      )}</ul>
      {error.candidate_id && <p className="mt-1 break-all">Candidate: <code>{error.candidate_id}</code> · Lần thử {(error.attempt ?? 0) + 1}</p>}
    </div>}
    {review.requirement && <div className="mt-2"><strong>Yêu cầu đã đối chiếu</strong><p className="whitespace-pre-wrap break-words">{review.requirement}</p></div>}
    {review.variant_id && <p className="mt-2">Biến thể: <code>{review.variant_id}</code></p>}
    {!!Object.keys(review.criteria || {}).length && <div className="mt-2">
      <strong>Tiêu chí của biến thể</strong>
      <ul className="mt-1 list-disc pl-4">{Object.entries(review.criteria || {}).map(([key, value]) =>
        <li key={key}>{CRITERIA[key] || key}: {VALUES[value] || value}</li>)}</ul>
    </div>}
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
    {!!review.handoffs?.length && <details className="mt-2">
      <summary className="cursor-pointer">Lịch sử giao việc giữa các agent</summary>
      <ol className="mt-2 list-decimal space-y-1 pl-4">{review.handoffs.map(message => <li key={message.message_id}>
        {ROLES[message.sender] || message.sender} → {ROLES[message.recipient] || message.recipient}: {INTENTS[message.intent] || message.intent} · Lượt {message.attempt + 1}
      </li>)}</ol>
    </details>}
  </details>;
}
