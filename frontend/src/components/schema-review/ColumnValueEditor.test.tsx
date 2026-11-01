import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';

import { getColumnValueMappingsApi, reviewColumnValueMappingsApi, updateColumnValueMappingsApi } from '@/lib/api';
import { ColumnValueEditor } from './ColumnValueProposals';

vi.mock('@/lib/api', () => ({
  getColumnValueMappingsApi: vi.fn(),
  updateColumnValueMappingsApi: vi.fn(),
  reviewColumnValueMappingsApi: vi.fn(),
}));

afterEach(() => { cleanup(); vi.clearAllMocks(); });

it('reloads column values using the icon button', async () => {
  vi.mocked(getColumnValueMappingsApi).mockResolvedValue({ column_id: 21, complete: false, version: 'v1', items: [] });
  render(<ColumnValueEditor dbId="7" columnId={21} columnName="status" canManage canApprove />);
  fireEvent.click(screen.getByRole('button', { name: /Giá trị nghiệp vụ/ }));
  const reload = await screen.findByRole('button', { name: 'Tải lại giá trị' });
  expect(reload.querySelector('svg')).toBeInTheDocument();
  expect(reload.parentElement).toContainElement(screen.getByRole('button', { name: /Giá trị nghiệp vụ/ }));
  fireEvent.click(reload);
  await waitFor(() => expect(getColumnValueMappingsApi).toHaveBeenCalledTimes(2));
});

it('requires a scope and approves edited values together', async () => {
  vi.mocked(getColumnValueMappingsApi).mockResolvedValue({ column_id: 21, complete: false, version: 'v1', items: [
    { db_value: 1, business_value: 'Old', source: 'manual', status: 'pending' },
  ] });
  vi.mocked(reviewColumnValueMappingsApi).mockResolvedValue({ updated: 1, version: 'v2' });
  render(<ColumnValueEditor dbId="7" columnId={21} columnName="status" canManage canApprove />);
  fireEvent.click(screen.getByRole('button', { name: /Gi\u00e1 tr\u1ecb nghi\u1ec7p v\u1ee5/ }));
  const meaning = await screen.findByRole('textbox', { name: /\u00dd ngh\u0129a nghi\u1ec7p v\u1ee5 1/ });
  const approve = screen.getByRole('button', { name: 'Duy\u1ec7t gi\u00e1 tr\u1ecb' });
  expect(approve).toBeDisabled();
  fireEvent.change(meaning, { target: { value: 'New' } });
  fireEvent.click(screen.getByRole('radio', { name: '\u0110\u1ea7y \u0111\u1ee7' }));
  fireEvent.click(approve);
  await waitFor(() => expect(reviewColumnValueMappingsApi).toHaveBeenCalledWith('7', 21, [], 'approve', 'v1', {
    items: [{ db_value: 1, business_value: 'New' }], complete: true,
  }));
  expect(updateColumnValueMappingsApi).not.toHaveBeenCalled();
});

it('shows legacy values and only loads when opened', async () => {
  vi.mocked(getColumnValueMappingsApi).mockResolvedValue({ column_id: 21, complete: true, version: 'v1', items: [
    { db_value: false, business_value: '', source: 'legacy', status: 'approved' },
  ] });
  render(<ColumnValueEditor dbId="7" columnId={21} columnName="status" canManage canApprove={false} />);
  expect(getColumnValueMappingsApi).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: /Giá trị nghiệp vụ/ }));
  expect(await screen.findByText(/Giá trị cũ/)).toBeInTheDocument();
  expect(screen.getByRole('textbox', { name: /Giá trị DB 1/ })).toHaveValue('false');
});

it('keeps a draft on approval conflict', async () => {
  vi.mocked(getColumnValueMappingsApi).mockResolvedValue({ column_id: 21, complete: false, version: 'v1', items: [
    { db_value: 'paid', business_value: 'Paid', source: 'manual', status: 'pending' },
  ] });
  vi.mocked(reviewColumnValueMappingsApi).mockRejectedValue(Object.assign(new Error('conflict'), { status: 409 }));
  render(<ColumnValueEditor dbId="7" columnId={21} columnName="status" canManage canApprove />);
  fireEvent.click(screen.getByRole('button', { name: /Gi\u00e1 tr\u1ecb nghi\u1ec7p v\u1ee5/ }));
  const meaning = await screen.findByRole('textbox', { name: /\u00dd ngh\u0129a nghi\u1ec7p v\u1ee5 1/ });
  fireEvent.change(meaning, { target: { value: 'Updated' } });
  fireEvent.click(screen.getByRole('radio', { name: 'Tham kh\u1ea3o' }));
  fireEvent.click(screen.getByRole('button', { name: 'Duy\u1ec7t gi\u00e1 tr\u1ecb' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('B\u1ea3n nh\u00e1p v\u1eabn \u0111\u01b0\u1ee3c gi\u1eef');
  expect(meaning).toHaveValue('Updated');
});
