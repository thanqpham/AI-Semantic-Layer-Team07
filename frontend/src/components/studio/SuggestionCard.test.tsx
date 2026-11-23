import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { SuggestionCard } from '@/components/studio/SuggestionCard';
import { reviewedSuggestionFields } from '@/test/metricReviewFixture';
import type { MetricSuggestion, SuggestionLifecycle } from '@/lib/api';

function makeSuggestion(): MetricSuggestion {
  return {
    ...reviewedSuggestionFields,
    definition: {
      metric: {
        name: 'Doanh thu trước thuế',
        formula: { function: 'SUM', expression: 'amount' },
        base_entity: 'orders',
        filters: [],
        status: 'pending_approval',
        confidence: 'high',
      },
    },
    yaml_preview: '',
  } as unknown as MetricSuggestion;
}

function renderCard(lifecycle?: SuggestionLifecycle | null, catalogNameConflict = false) {
  return render(
    <SuggestionCard
      suggestion={makeSuggestion()}
      lifecycle={lifecycle}
      catalogNameConflict={catalogNameConflict}
      onSave={vi.fn().mockResolvedValue(undefined)}
      onOpenCatalog={vi.fn()}
    />,
  );
}

describe('SuggestionCard lifecycle states', () => {
  beforeEach(() => {
    cleanup();
  });

  it('shows the numerator, denominator and scaling for a ratio', () => {
    const suggestion = makeSuggestion();
    suggestion.definition.metric.formula.ratio = {
      numerator: { function: 'SUM', expression: 'amount' },
      denominator: { function: 'COUNT_DISTINCT', expression: 'id' }, scale: 100, offset: 1,
    };
    render(<SuggestionCard suggestion={suggestion} catalogNameConflict={false} onSave={vi.fn()} />);
    expect(screen.getByText(/1 \+ 100 × \(SUM\(amount\)\) \/ \(COUNT_DISTINCT\(id\)\)/)).toBeInTheDocument();
  });

  it('shows only the calculation without grouping details or query plan YAML', () => {
    const suggestion = makeSuggestion();
    suggestion.definition.metric.query_plan = {
      output_expression: 'per_product.order_count',
      stages: [{ name: 'per_product', base_entity: 'order_items', joins: [],
        group_by: [{ name: 'product_id', expression: 'order_items.product_id', column_id: 580 }],
        aggregates: [{ name: 'order_count', function: 'COUNT_DISTINCT', expression: 'order_items.order_id', filters: [] }], filters: [] }],
    };
    render(<SuggestionCard suggestion={suggestion} catalogNameConflict={false} onSave={vi.fn()} />);
    expect(screen.getByText('COUNT_DISTINCT(order_items.order_id)')).toBeInTheDocument();
    expect(screen.queryByText(/Nhóm theo/)).not.toBeInTheDocument();
    expect(screen.queryByText(/per_product.order_count/)).not.toBeInTheDocument();
    expect(screen.queryByText(/column_id:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/source_stage:/)).not.toBeInTheDocument();
  });

  it('shows the output and intermediate calculations for a multi-stage plan', () => {
    const suggestion = makeSuggestion();
    suggestion.definition.metric.query_plan = {
      output_expression: 'repeat.customers / total.customers',
      stages: [
        { name: 'repeat', base_entity: 'orders', joins: [], group_by: [],
          aggregates: [{ name: 'customers', function: 'COUNT_DISTINCT', expression: 'orders.customer_id', filters: [] }], filters: [] },
        { name: 'total', base_entity: 'orders', joins: [], group_by: [],
          aggregates: [{ name: 'customers', function: 'COUNT', expression: '*', filters: [] }], filters: [] },
      ],
    };
    render(<SuggestionCard suggestion={suggestion} catalogNameConflict={false} onSave={vi.fn()} />);
    expect(screen.getByText('repeat.customers / total.customers')).toBeInTheDocument();
    expect(screen.getByText('repeat.customers = COUNT_DISTINCT(orders.customer_id)')).toBeInTheDocument();
    expect(screen.getByText('total.customers = COUNT(*)')).toBeInTheDocument();
  });

  it('lists stage and aggregate filters with their separate scopes', () => {
    const suggestion = makeSuggestion();
    suggestion.definition.metric.query_plan = {
      output_expression: 'totals.revenue', stages: [{ name: 'totals', base_entity: 'orders', joins: [], group_by: [],
        filters: [{ field: 'orders.status', operator: 'eq', value: '' }],
        aggregates: [{ name: 'revenue', function: 'SUM', expression: 'orders.amount',
          filters: [{ field: 'orders.region', operator: 'in', value: ['north', 'south'] }] }] }],
    };
    render(<SuggestionCard suggestion={suggestion} catalogNameConflict={false} onSave={vi.fn()} />);
    expect(screen.getByText('Bước totals: orders.status = ""')).toBeInTheDocument();
    expect(screen.getByText('Bước totals, phép tính revenue: orders.region thuộc ["north", "south"]')).toBeInTheDocument();
    expect(screen.queryByText('Không có bộ lọc')).not.toBeInTheDocument();
  });

  it('fresh suggestion: black save button, no status pill, no reject-reason tab', () => {
    renderCard(undefined);

    expect(screen.getByRole('button', { name: 'Lưu vào Semantic Layer' })).toBeInTheDocument();
    expect(screen.queryByText('Chờ duyệt')).toBeNull();
    expect(screen.queryByText('Đã duyệt')).toBeNull();
    expect(screen.queryByText('Đã từ chối')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Lý do từ chối' })).toBeNull();
  });

  it('pending: green saved button + "Chờ duyệt" pill, no amber strip even on catalog name conflict', () => {
    renderCard({ metric_id: 7, metric_status: 'pending_approval', rejection_reason: null }, true);

    expect(screen.getByRole('button', { name: 'Đã lưu — mở catalog' })).toBeInTheDocument();
    expect(screen.getByText('Chờ duyệt')).toBeInTheDocument();
    expect(screen.queryByText(/Tên này đã có trong catalog/)).toBeNull();
  });

  it('approved: "Đã duyệt" pill and green catalog button', () => {
    renderCard({ metric_id: 7, metric_status: 'approved', rejection_reason: null });

    expect(screen.getByText('Đã duyệt')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Đã lưu — mở catalog' })).toBeInTheDocument();
  });

  it('rejected: black save button, "Đã từ chối" pill, reason tab reveals reason, no amber strip', () => {
    // Real backend payload: a rejected proposal is released, so metric_id and
    // metric_status are both null and only rejection_reason is set
    // (see tests/test_api/test_chat_session_lifecycle.py payload[3]).
    renderCard(
      { metric_id: null, metric_status: null, rejection_reason: 'Công thức trùng metric khác' },
      true,
    );

    expect(screen.getByRole('button', { name: 'Lưu vào Semantic Layer' })).toBeInTheDocument();
    expect(screen.getByText('Đã từ chối')).toBeInTheDocument();
    expect(screen.queryByText(/Tên này đã có trong catalog/)).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Lý do từ chối' }));
    expect(screen.getByText('Công thức trùng metric khác')).toBeInTheDocument();
  });

  it('no longer renders the confidence chip', () => {
    renderCard(undefined);

    expect(screen.queryByText(/Độ tin cậy/)).toBeNull();
  });

  it('embedded cards carry a bottom separator so stacked suggestions do not merge', () => {
    const { container } = render(
      <SuggestionCard
        suggestion={makeSuggestion()}
        embedded
        catalogNameConflict={false}
        onSave={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    const root = container.firstElementChild as HTMLElement;
    expect(root.className).toContain('border-b');
    expect(root.className).toContain('last:border-b-0');
  });

  it('shows the save failure on the card instead of only flickering the button', async () => {
    render(
      <SuggestionCard
        suggestion={makeSuggestion()}
        catalogNameConflict={false}
        onSave={vi.fn().mockRejectedValue(new Error('Metric với tên "Doanh thu trước thuế" đã tồn tại'))}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Lưu vào Semantic Layer' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/đã tồn tại/);
    // The card stays unsaved — black save button returns after the flicker.
    expect(screen.getByRole('button', { name: 'Lưu vào Semantic Layer' })).toBeInTheDocument();
  });
});
