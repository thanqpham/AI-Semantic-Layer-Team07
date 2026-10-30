import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';

import type { EnrichStatus } from '@/lib/api';
import { EnrichmentProgressBanner } from './EnrichmentProgressBanner';

afterEach(() => { cleanup(); vi.clearAllMocks(); });

function status(partial: Partial<EnrichStatus>): EnrichStatus {
  return {
    db_id: 1, status: 'running', phase: 'analyzing', total_tables: 0, completed_tables: 0,
    current_table: null, error: null, started_at: null, finished_at: null,
    ...partial,
  };
}

it('renders nothing when idle', () => {
  const { container } = render(
    <EnrichmentProgressBanner status={status({ status: 'idle' })} onRetry={() => {}} />,
  );
  expect(container).toBeEmptyDOMElement();
});

it('shows an indeterminate banner while analyzing', () => {
  render(<EnrichmentProgressBanner status={status({ phase: 'analyzing' })} onRetry={() => {}} />);
  expect(screen.getByText('⚡ Đang phân tích schema…')).toBeInTheDocument();
  expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
});

it('shows completed/total counts, current table and a 50% bar while generating', () => {
  render(
    <EnrichmentProgressBanner
      status={status({ phase: 'generating', total_tables: 10, completed_tables: 5, current_table: 'orders' })}
      onRetry={() => {}}
    />,
  );
  expect(screen.getByText(/Đang tạo mô tả AI/)).toBeInTheDocument();
  expect(screen.getByText(/5\/10/)).toBeInTheDocument();
  expect(screen.getByText(/orders/)).toBeInTheDocument();
  expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '50');
});

it('shows the error and retries on click when failed', () => {
  const onRetry = vi.fn();
  render(
    <EnrichmentProgressBanner
      status={status({ status: 'failed', error: 'LLM down' })}
      onRetry={onRetry}
    />,
  );
  expect(screen.getByText(/LLM down/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Thử lại' }));
  expect(onRetry).toHaveBeenCalledTimes(1);
});

it('shows the success banner', () => {
  render(
    <EnrichmentProgressBanner status={status({ status: 'succeeded' })} onRetry={() => {}} />,
  );
  expect(screen.getByText(/Đã tạo mô tả xong/)).toBeInTheDocument();
});
