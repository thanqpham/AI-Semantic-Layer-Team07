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
