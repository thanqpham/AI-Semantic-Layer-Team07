import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';

import { ColumnValueProposals } from './ColumnValueProposals';
import { getColumnValueProposalsApi, reviewColumnValueProposalsApi, scanColumnValueProposalsApi, setColumnValueDiscoveryApi } from '@/lib/api';

vi.mock('@/lib/api', () => ({
  getColumnValueProposalsApi: vi.fn(),
  reviewColumnValueProposalsApi: vi.fn(),
  scanColumnValueProposalsApi: vi.fn(),
  setColumnValueDiscoveryApi: vi.fn(),
}));

afterEach(() => { cleanup(); vi.clearAllMocks(); });

it('reviews selected screened proposals in bulk', async () => {
  vi.mocked(getColumnValueProposalsApi).mockResolvedValue({ enabled: true, available: true, items: [
    { id: 1, column_id: 3, table_name: 'orders', physical_schema: 'public', column_name: 'status',
      source: 'observed', status: 'pending', values: ['completed', 'cancelled'], observed_at: null },
    { id: 2, column_id: 4, table_name: 'orders', physical_schema: 'public', column_name: 'channel',
      source: 'declared', status: 'pending', values: ['web'], observed_at: null },
  ] });
  vi.mocked(reviewColumnValueProposalsApi).mockResolvedValue({ updated: 2 });
  render(<ColumnValueProposals dbId="7" canManage canApprove />);
  expect(await screen.findByText('completed, cancelled')).toBeInTheDocument();
  expect(screen.getByText(/có thể chưa đầy đủ/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('checkbox', { name: 'Chọn public.orders.status' }));
  fireEvent.click(screen.getByRole('checkbox', { name: 'Chọn public.orders.channel' }));
  fireEvent.click(screen.getByRole('button', { name: /Xác nhận giá trị/ }));
  await waitFor(() => expect(reviewColumnValueProposalsApi).toHaveBeenCalledWith('7', [1, 2], 'approve'));
});

it('restricts actions and hides blocked values', async () => {
  vi.mocked(getColumnValueProposalsApi).mockResolvedValue({ enabled: true, available: true, items: [
    { id: 3, column_id: 5, table_name: 'orders', physical_schema: null, column_name: 'status',
      source: 'observed', status: 'blocked', values: ['sensitive@example.com'], observed_at: null },
  ] });
  render(<ColumnValueProposals dbId="7" canManage canApprove={false} />);
  await screen.findByText('orders.status');
  expect(screen.queryByText('sensitive@example.com')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: /Xác nhận giá trị/ })).toBeDisabled();
  expect(screen.getByRole('button', { name: /Bỏ qua/ })).toBeDisabled();
  expect(scanColumnValueProposalsApi).not.toHaveBeenCalled();
});

it('starts a background scan and reports a safe error without rendering provider details', async () => {
  vi.mocked(getColumnValueProposalsApi).mockResolvedValue({ enabled: true, available: true, items: [] });
  vi.mocked(scanColumnValueProposalsApi).mockRejectedValue(new Error('sensitive@example.com'));
  render(<ColumnValueProposals dbId="7" canManage canApprove />);
  await screen.findByText('Chưa có đề xuất giá trị.');
  fireEvent.click(screen.getByRole('button', { name: 'Quét lại' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Không thể bắt đầu quét');
  expect(screen.queryByText('sensitive@example.com')).not.toBeInTheDocument();
});

it('requires enabling discovery before scan and respects availability', async () => {
  vi.mocked(getColumnValueProposalsApi).mockResolvedValue({ enabled: false, available: true, items: [] });
  vi.mocked(setColumnValueDiscoveryApi).mockResolvedValue({ enabled: true });
  render(<ColumnValueProposals dbId="7" canManage canApprove />);
  await screen.findByText('Chưa có đề xuất giá trị.');
  expect(screen.getByRole('button', { name: 'Quét lại' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Bật khám phá tự động' }));
  await waitFor(() => expect(setColumnValueDiscoveryApi).toHaveBeenCalledWith('7', true));
  expect(screen.getByRole('button', { name: 'Quét lại' })).toBeEnabled();
});
