import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { getColumnValueMappingsApi, previewValueMappingBatchApi, updateColumnValueMappingsApi, type SchemaReview } from '@/lib/api';
import { ValueMappingBatchImport } from './ValueMappingBatchImport';

vi.mock('@/lib/api', () => ({
  getColumnValueMappingsApi: vi.fn(), previewValueMappingBatchApi: vi.fn(), updateColumnValueMappingsApi: vi.fn(),
}));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

it('opens the file picker from the import button and respects permissions', () => {
  const review = { tables: [] } as unknown as SchemaReview;
  const click = vi.spyOn(HTMLInputElement.prototype, 'click').mockImplementation(() => {});
  const { rerender } = render(<ValueMappingBatchImport dbId="10" review={review} canManage />);
  fireEvent.click(screen.getByRole('button', { name: 'Nạp giá trị nghiệp vụ' }));
  expect(click).toHaveBeenCalledOnce();
  const toggle = screen.getByRole('button', { name: 'Chi tiết nạp giá trị nghiệp vụ' });
  expect(toggle).toHaveAttribute('aria-expanded', 'false');
  fireEvent.click(toggle);
  expect(toggle).toHaveAttribute('aria-expanded', 'true');
  expect(click).toHaveBeenCalledOnce();
  rerender(<ValueMappingBatchImport dbId="10" review={review} canManage={false} />);
  expect(screen.getByRole('button', { name: 'Nạp giá trị nghiệp vụ' })).toBeDisabled();
  expect(screen.queryByRole('button', { name: 'Chọn file' })).not.toBeInTheDocument();
  click.mockRestore();
});

it('closes the detail popup with Escape or an outside click', () => {
  const review = { tables: [] } as unknown as SchemaReview;
  render(<><button>Ngoài popup</button><ValueMappingBatchImport dbId="10" review={review} canManage /></>);
  const toggle = screen.getByRole('button', { name: 'Chi tiết nạp giá trị nghiệp vụ' });
  fireEvent.click(toggle);
  expect(screen.getByText('Nạp giá trị cho nhiều cột')).toBeVisible();
  expect(document.getElementById(toggle.getAttribute('aria-controls')!)).toHaveClass('absolute');
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(toggle).toHaveAttribute('aria-expanded', 'false');
  expect(toggle).toHaveFocus();
  fireEvent.click(toggle);
  fireEvent.pointerDown(screen.getByRole('button', { name: 'Ngoài popup' }));
  expect(toggle).toHaveAttribute('aria-expanded', 'false');
});

it('previews several columns and saves without overwriting existing meanings', async () => {
  const review = { tables: [{ table_name: 'orders', columns: [{ column_id: 21, column_name: 'status' }] }] } as SchemaReview;
  vi.mocked(previewValueMappingBatchApi).mockResolvedValue({ columns: [{ column_id: 21, items: [
    { db_value: 'paid', business_value: 'Khác' }, { db_value: 'new', business_value: 'Mới' },
  ] }] });
  vi.mocked(getColumnValueMappingsApi).mockResolvedValue({ column_id: 21, version: 'v1', complete: true, items: [
    { db_value: 'paid', business_value: 'Đã trả', source: 'manual', status: 'approved' },
  ] });
  vi.mocked(updateColumnValueMappingsApi).mockResolvedValue({ column_id: 21, version: 'v2', complete: false, items: [] });
  render(<ValueMappingBatchImport dbId="10" review={review} canManage />);
  fireEvent.click(screen.getByRole('button', { name: 'Nạp giá trị nghiệp vụ' }));
  fireEvent.change(screen.getByLabelText('Nạp file cho nhiều cột'), { target: { files: [new File(['{}'], 'values.json')] } });
  expect(await screen.findByText('Xem trước 1 cột')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Chi tiết nạp giá trị nghiệp vụ' })).toHaveAttribute('aria-expanded', 'true');
  expect(updateColumnValueMappingsApi).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Lưu các giá trị chờ duyệt' }));
  await waitFor(() => expect(updateColumnValueMappingsApi).toHaveBeenCalledWith('10', 21, [
    { db_value: 'paid', business_value: 'Đã trả' }, { db_value: 'new', business_value: 'Mới' },
  ], false, 'v1'));
});

it('reports partial saves when a later column conflicts', async () => {
  const review = { tables: [] } as unknown as SchemaReview;
  vi.mocked(previewValueMappingBatchApi).mockResolvedValue({ columns: [
    { column_id: 21, items: [{ db_value: 'a', business_value: 'A' }] },
    { column_id: 22, items: [{ db_value: 'b', business_value: 'B' }] },
  ] });
  vi.mocked(getColumnValueMappingsApi).mockResolvedValue({ column_id: 21, version: 'v1', complete: false, items: [] });
  vi.mocked(updateColumnValueMappingsApi)
    .mockResolvedValueOnce({ column_id: 21, version: 'v2', complete: false, items: [] })
    .mockRejectedValueOnce(new Error('conflict'));
  render(<ValueMappingBatchImport dbId="10" review={review} canManage />);
  fireEvent.click(screen.getByRole('button', { name: 'Nạp giá trị nghiệp vụ' }));
  fireEvent.change(screen.getByLabelText('Nạp file cho nhiều cột'), { target: { files: [new File(['{}'], 'values.json')] } });
  await screen.findByText('Xem trước 2 cột');
  fireEvent.click(screen.getByRole('button', { name: 'Lưu các giá trị chờ duyệt' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Đã lưu 1/2 cột');
});
