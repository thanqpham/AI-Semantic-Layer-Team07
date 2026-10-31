import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { MetricReviewPanel } from './MetricReviewPanel';
import { StudioChatStream } from '@/components/studio/StudioChatStream';
import { MetricModal } from '@/components/modals/MetricModal';
import type { MetricDefinition, MetricSuggestion } from '@/lib/api';
import { passingReview, reviewedSuggestionFields } from '@/test/metricReviewFixture';

afterEach(cleanup);

const definition: MetricDefinition = { metric: { name: 'Doanh thu', base_entity: 'orders',
  formula: { function: 'SUM', expression: 'amount' }, filters: [], status: 'pending_approval', confidence: 'high', excluded_notes: '' } };

describe('metric review evidence and gates', () => {
  it('shows the invalid reviewer field, candidate and attempt', () => {
    render(<MetricReviewPanel review={{ ...passingReview, status: 'error', execution_error: {
      code: 'INVALID_AGENT_OUTPUT', stage: 'reviewer', message: 'Phản hồi sai cấu trúc.', retryable: false,
      candidate_id: 'candidate-123', attempt: 1,
      validation_errors: [{ field: 'issues.0.action', type: 'missing', message: 'Field required' }],
    } }} />);
    fireEvent.click(screen.getByText('AI chưa trả được thẩm định hợp lệ'));
    expect(screen.getByText('issues.0.action')).toBeInTheDocument();
    expect(screen.getByText('missing')).toBeInTheDocument();
    expect(screen.getByText('candidate-123')).toBeInTheDocument();
    expect(screen.getByText(/Lần thử 2/)).toBeInTheDocument();
  });
  it('shows the reviewed variant and its business criteria', () => {
    render(<MetricReviewPanel review={{ ...passingReview, variant_id: 'merchandise_net_including_vat',
      criteria: { tax_basis: 'includes_vat' } }} />);
    fireEvent.click(screen.getByText('AI đã thẩm định — chờ người duyệt'));
    expect(screen.getByText('merchandise_net_including_vat')).toBeInTheDocument();
    expect(screen.getByText('Cơ sở thuế: Gồm VAT')).toBeInTheDocument();
  });
  it('shows a structured reason category when one is available', () => {
    render(<MetricReviewPanel review={{ ...passingReview, status: 'needs_clarification',
      reason_code: 'UNRESOLVED_ASSUMPTION' }} />);
    fireEvent.click(screen.getByText('Cần xác nhận nghiệp vụ'));
    expect(screen.getByText('Nhóm lý do:').parentElement).toHaveTextContent('Còn giả định nghiệp vụ chưa xác nhận');
  });
  it.each([
    ['INVALID_AGENT_OUTPUT', 'AI chưa tạo được định nghĩa hợp lệ'],
    ['RATE_LIMITED', 'Đang bị giới hạn API'],
    ['QUOTA_EXHAUSTED', 'Tài khoản LLM đã hết quota'],
  ] as const)('distinguishes %s from a business revision', (code, label) => {
    render(<MetricReviewPanel review={{ ...passingReview, status: 'error', execution_error: {
      code, stage: 'builder', message: 'Không thể hoàn tất bước model.', retryable: code === 'RATE_LIMITED',
    } }} />);
    expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.queryByText('Cần sửa trước khi gửi duyệt')).not.toBeInTheDocument();
  });

  it('keeps a passing KPI actionable when another KPI failed', () => {
    render(<StudioChatStream messages={[{ id: 'partial', sender: 'assistant', text: '', timestamp: '', runStatus: 'partial',
      suggestions: [{ ...reviewedSuggestionFields, definition, yaml_preview: '' }],
      blockedCandidates: [{ name: 'KPI bị giới hạn', review: { ...passingReview, status: 'error', execution_error: {
        code: 'RATE_LIMITED', stage: 'reviewer', message: 'Đợi API', retryable: true, retry_after_seconds: 60,
      } } }],
    }]} onSendMessage={vi.fn()} isLoading={false} tableNames={[]} onAddMetric={vi.fn()} />);
    expect(screen.getByRole('status')).toHaveTextContent('Một phần tác vụ đã hoàn tất');
    expect(screen.getByRole('button', { name: 'Lưu vào Semantic Layer' })).toBeEnabled();
    expect(screen.queryByText('KPI bị giới hạn')).not.toBeInTheDocument();
  });

  it('shows the typed handoff history without exposing payloads', () => {
    render(<MetricReviewPanel review={{ ...passingReview, handoffs: [{ message_id: 'm', task_id: 't', candidate_id: 'c',
      sender: 'coordinator', recipient: 'metric_builder', intent: 'request', attempt: 0 }] }} />);
    fireEvent.click(screen.getByText('AI đã thẩm định — chờ người duyệt'));
    fireEvent.click(screen.getByText('Lịch sử giao việc giữa các agent'));
    expect(screen.getByText(/Metric Workflow Coordinator → Metric Designer Agent: Giao việc/)).toBeInTheDocument();
  });
  it('shows original requirements, evidence, curated links and before/after definitions', () => {
    render(<MetricReviewPanel definition={definition} review={{ ...passingReview, revised: true, repair_count: 1,
      original_definition: { metric: { formula: { expression: 'missing' } } },
      issues: [{ code: 'COLUMN', message: 'Đã sửa cột', evidence: 'amount có trong schema', action: 'Dùng amount' }],
      sources: [{ id: 'sales', title: 'Shopify Sales', url: 'https://help.shopify.com/', reviewed_at: '2026-10-23' }],
    }} />);
    fireEvent.click(screen.getByText('AI đã thẩm định — chờ người duyệt'));
    expect(screen.getByText(passingReview.requirement)).toBeInTheDocument();
    expect(screen.getByText(/amount có trong schema/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Shopify Sales' })).toHaveAttribute('href', 'https://help.shopify.com/');
    fireEvent.click(screen.getByText('Định nghĩa trước và sau thẩm định'));
    expect(screen.getByLabelText('Định nghĩa ban đầu')).toHaveTextContent('missing');
    expect(screen.getByLabelText('Định nghĩa cuối')).toHaveTextContent('amount');
    expect(screen.getByText('Đã dùng 1/1 lượt sửa.')).toBeInTheDocument();
  });

  it.each(['legacy', 'error', 'unsupported'] as const)('hides unsaveable %s suggestions', status => {
    const suggestion: MetricSuggestion = { definition, yaml_preview: '', ...(status === 'legacy' ? {} : {
      ...reviewedSuggestionFields, review: { ...passingReview, status },
    }) };
    render(<StudioChatStream messages={[{ id: 'message', sender: 'assistant', text: '', timestamp: '', suggestions: [suggestion] }]}
      onSendMessage={vi.fn()} isLoading={false} tableNames={[]} onAddMetric={vi.fn()} />);
    expect(screen.queryByText('Doanh thu')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Lưu vào Semantic Layer' })).not.toBeInTheDocument();
    expect(screen.getByText('Chưa tạo được metric có thể lưu.')).toBeInTheDocument();
  });

  it('hides blocked candidates after history reload', () => {
    render(<StudioChatStream messages={[{ id: 'reloaded', sender: 'assistant', text: '', timestamp: '',
      blockedCandidates: [{ name: 'Biên lợi nhuận', review: { ...passingReview, status: 'rejected', summary: 'Thiếu giá vốn' } }],
    }]} onSendMessage={vi.fn()} isLoading={false} tableNames={[]} />);
    expect(screen.queryByText('Biên lợi nhuận')).not.toBeInTheDocument();
    expect(screen.getByText('Chưa tạo được metric có thể lưu.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Lưu vào Semantic Layer' })).not.toBeInTheDocument();
  });

  it.each(['rejected', 'unsupported', 'needs_clarification'] as const)('explains a blocked requested metric: %s', status => {
    render(<StudioChatStream messages={[{ id: 'requested', sender: 'assistant', text: '', timestamp: '', proposalMode: 'requested',
      blockedCandidates: [{ name: 'Tỷ lệ hoàn tiền', review: { ...passingReview, status,
        summary: 'Cần dữ liệu hoàn tiền', issues: [{ code: 'MISSING', message: 'Thiếu dữ liệu', evidence: 'Không có cột', action: 'Bổ sung cột hoàn tiền' }] } }],
    }]} onSendMessage={vi.fn()} isLoading={false} tableNames={[]} onAddMetric={vi.fn()} />);
    expect(screen.getByText('Cần dữ liệu hoàn tiền')).toBeInTheDocument();
    expect(screen.getByText('Lý do chưa tạo được metric')).toBeInTheDocument();
    expect(screen.getByText('Cần làm')).toBeInTheDocument();
    expect(screen.getByText(/Bổ sung cột hoàn tiền/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Lưu vào Semantic Layer' })).not.toBeInTheDocument();
  });

  it('preserves conversation clarification when all candidates are blocked', () => {
    render(<StudioChatStream messages={[{ id: 'clarify', sender: 'assistant', text: 'Bạn muốn tính kỳ nào?', timestamp: '',
      clarification: { prompt: 'Bạn muốn tính kỳ nào?', options: [{ id: 'month', label: 'Theo tháng' }] },
      blockedCandidates: [{ name: 'Không thể tạo', review: { ...passingReview, status: 'needs_clarification' } }],
    }]} onSendMessage={vi.fn()} isLoading={false} tableNames={[]} />);
    expect(screen.getByText('Bạn muốn tính kỳ nào?')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Theo tháng' })).toBeInTheDocument();
    expect(screen.queryByText('Không thể tạo')).not.toBeInTheDocument();
  });

  it('shows the clarification prompt even without options when candidates are blocked', () => {
    render(<StudioChatStream messages={[{ id: 'clarify-empty', sender: 'assistant', text: 'Các KPI dưới đây chưa đủ điều kiện.', timestamp: '',
      clarification: { prompt: 'Bạn muốn tính kỳ nào?', options: [] },
      blockedCandidates: [{ name: 'Không thể tạo', review: { ...passingReview, status: 'needs_clarification' } }],
    }]} onSendMessage={vi.fn()} isLoading={false} tableNames={[]} />);
    expect(screen.getByText('Bạn muốn tính kỳ nào?')).toBeInTheDocument();
    expect(screen.queryByText('Các KPI dưới đây chưa đủ điều kiện.')).not.toBeInTheDocument();
  });

  it('keeps duplicate guidance when blocked candidates are hidden', () => {
    render(<StudioChatStream messages={[{ id: 'duplicate-blocked', sender: 'assistant', text: 'Chỉ số đã có sẵn.', timestamp: '',
      duplicates: [{ existing_metric_id: 1, existing_metric_name: 'AOV', existing_metric_status: 'approved', user_message: 'AOV đã tồn tại', similarity_reason: 'Giống công thức' }],
      blockedCandidates: [{ name: 'Không thể tạo', review: { ...passingReview, status: 'rejected' } }],
    }]} onSendMessage={vi.fn()} isLoading={false} tableNames={[]} />);
    expect(screen.getByText('Chỉ số đã có sẵn.')).toBeInTheDocument();
    expect(screen.queryByText('Không thể tạo')).not.toBeInTheDocument();
  });

  it('shows a general message when an error response references hidden candidates', () => {
    render(<StudioChatStream messages={[{ id: 'error-blocked', sender: 'assistant', text: 'Các KPI dưới đây chưa đủ điều kiện gửi duyệt.', timestamp: '', runStatus: 'error',
      blockedCandidates: [{ name: 'Không thể tạo', review: { ...passingReview, status: 'error' } }],
    }]} onSendMessage={vi.fn()} isLoading={false} tableNames={[]} />);
    expect(screen.getByText('Không thể hoàn tất đề xuất metric do lỗi xử lý. Vui lòng thử lại.')).toBeInTheDocument();
    expect(screen.queryByText('Không thể tạo')).not.toBeInTheDocument();
  });

  it('re-reviews a modal draft without saving or closing it', async () => {
    const review = vi.fn().mockResolvedValue(undefined), save = vi.fn(), close = vi.fn();
    render(<MetricModal isOpen tables={[]} initialDefinition={definition} review={passingReview}
      onClose={close} onSave={save} onReview={review} />);
    fireEvent.click(screen.getByRole('button', { name: 'Thẩm định lại bản sửa' }));
    expect(review).toHaveBeenCalledWith(definition);
    expect(save).not.toHaveBeenCalled();
    expect(close).not.toHaveBeenCalled();
  });
});
