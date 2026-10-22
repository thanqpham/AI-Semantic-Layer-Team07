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

  it.each(['legacy', 'error', 'unsupported'] as const)('prevents save for %s suggestions', status => {
    const suggestion: MetricSuggestion = { definition, yaml_preview: '', ...(status === 'legacy' ? {} : {
      ...reviewedSuggestionFields, review: { ...passingReview, status },
    }) };
    render(<StudioChatStream messages={[{ id: 'message', sender: 'assistant', text: '', timestamp: '', suggestions: [suggestion] }]}
      onSendMessage={vi.fn()} isLoading={false} tableNames={[]} onAddMetric={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Lưu vào Semantic Layer' })).toBeDisabled();
  });

  it('offers discovery and keeps blocked candidates visible after history reload', () => {
    const discover = vi.fn();
    render(<StudioChatStream messages={[{ id: 'reloaded', sender: 'assistant', text: '', timestamp: '',
      blockedCandidates: [{ name: 'Biên lợi nhuận', review: { ...passingReview, status: 'rejected', summary: 'Thiếu giá vốn' } }],
    }]} onSendMessage={vi.fn()} isLoading={false} tableNames={[]} onDiscoverMetrics={discover} />);
    fireEvent.click(screen.getByRole('button', { name: 'Khám phá KPI từ schema' }));
    expect(discover).toHaveBeenCalledOnce();
    expect(screen.getByText('Biên lợi nhuận')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Chưa phù hợp hoặc thiếu dữ liệu'));
    expect(screen.getByText('Thiếu giá vốn')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Lưu vào Semantic Layer' })).not.toBeInTheDocument();
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
