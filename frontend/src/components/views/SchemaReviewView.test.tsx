import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';

import {
  approveSchemaReviewApi,
  generateDescriptionsApi,
  getEnrichStatusApi,
  getSchemaReviewApi,
  getColumnValueMappingsApi,
  saveSchemaReviewBatchApi,
  type EnrichStatus,
  type SchemaReview,
} from '@/lib/api';
import { SchemaReviewView } from './SchemaReviewView';

const overviewMock = vi.hoisted(() => ({ described: null as boolean | null }));
vi.mock('@/components/schema-review/DatabaseOverview', async () => {
  const { useEffect } = await import('react');
  return {
    DatabaseOverview: ({ hidden, onDescribedChange }: { hidden?: boolean; onDescribedChange?: (value: boolean) => void }) => {
      useEffect(() => { if (overviewMock.described !== null) onDescribedChange?.(overviewMock.described); }, [onDescribedChange]);
      return <section aria-label="Tổng quan database" hidden={hidden} />;
    },
  };
});
vi.mock('@/components/schema-review/RelationshipsPanel', () => ({RelationshipsPanel:()=> <div>Relationship queue</div>}));
vi.mock('@/lib/api', () => ({
  getSchemaReviewApi: vi.fn(),
  approveSchemaReviewApi: vi.fn(),
  saveSchemaReviewBatchApi: vi.fn(),
  generateDescriptionsApi: vi.fn(),
  getEnrichStatusApi: vi.fn(),
  getColumnValueMappingsApi: vi.fn(),
  updateColumnValueMappingsApi: vi.fn(),
  reviewColumnValueMappingsApi: vi.fn(),
}));

const idleStatus: EnrichStatus = { db_id: 7, status: 'idle', phase: '', total_tables: 0, completed_tables: 0, current_table: null, error: null, started_at: null, finished_at: null };
const runningStatus: EnrichStatus = { ...idleStatus, status: 'running', phase: 'generating', total_tables: 10, completed_tables: 5, current_table: 'orders' };
const succeededStatus: EnrichStatus = { ...idleStatus, status: 'succeeded' };
const failedStatus: EnrichStatus = { ...idleStatus, status: 'failed', error: 'LLM down' };
const emptyReview: SchemaReview = { db_id: 7, status: 'pending_review', pending_tables: 0, pending_columns: 0, pending_relationships: 0, tables: [] };

afterEach(() => { cleanup(); vi.clearAllMocks(); overviewMock.described = null; });

it('keeps the full-width header outside the scrollable review content without shrinking', () => {
  const { container } = render(<SchemaReviewView />);
  const header = screen.getByRole('banner');
  const view = container.firstElementChild;
  const content = header.nextElementSibling;

  expect(view).toHaveClass('h-full', 'w-full', 'overflow-hidden');
  expect(header).toHaveClass('shrink-0');
  expect(content).toHaveClass('min-h-0', 'flex-1', 'overflow-y-auto');
});

it('shows pending relationship tab and bulk approves only tables and columns', async () => {
 vi.mocked(getSchemaReviewApi).mockResolvedValue({db_id:7,status:'pending_review',pending_tables:1,pending_columns:2,pending_relationships:3,tables:[]});
 vi.mocked(approveSchemaReviewApi).mockResolvedValue({db_id:7,status:'approved',approved_tables:1,approved_columns:2,pending_tables:0,pending_columns:0,pending_relationships:3});
 render(<SchemaReviewView dbId={7} canManageSchema canApproveSchema/>);
 const tab=await screen.findByRole('tab',{name:'Liên kết (3)'});fireEvent.click(tab);expect(tab).toHaveAttribute('aria-selected','true');
 expect(screen.getByRole('tabpanel', { name: /Liên kết/ })).toHaveClass('min-h-[560px]', 'shrink-0');
 expect(screen.getByText('Relationship queue')).toBeVisible();expect(screen.getByRole('tab',{name:'Bảng & cột'})).toBeInTheDocument();
 expect(screen.queryByRole('button',{name:'Duyệt bảng & cột (3)'})).not.toBeInTheDocument();
 expect(screen.queryByRole('button',{name:'Tạo mô tả AI'})).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole('tab',{name:'Bảng & cột'}));
 expect(screen.getByRole('tablist').parentElement).toContainElement(screen.getByRole('button',{name:'Tạo mô tả AI'}));
 fireEvent.click(screen.getByRole('button',{name:'Duyệt bảng & cột (3)'}));
 await waitFor(()=>expect(approveSchemaReviewApi).toHaveBeenCalledWith('7',undefined,undefined));
 expect(screen.getByText(/liên kết chờ xác nhận riêng/)).toHaveTextContent('3');
});


it('does not advertise or load a read-only review queue without schema permission', () => {
 vi.mocked(getSchemaReviewApi).mockClear();
 render(<SchemaReviewView dbId={7} />);
 expect(screen.getByRole('status')).toHaveTextContent('Schema Review requires schema management permission');
 expect(screen.queryByText('Relationship queue')).not.toBeInTheDocument();
 expect(getSchemaReviewApi).not.toHaveBeenCalled();
});

const col = (id: number, name: string, extra: Partial<SchemaReview['tables'][0]['columns'][0]> = {}) => ({
  column_id: id, column_name: name, business_name: name, description: '', data_type: 'TEXT',
  review_status: 'pending_review' as const, is_primary_key: false, is_time_dimension: false, ...extra,
});
const twoTables: SchemaReview = { db_id: 7, status: 'pending_review', pending_tables: 1, pending_columns: 2, pending_relationships: 0, tables: [
  { table_id: 11, table_name: 'orders', business_name: 'Đơn hàng', description: '', review_status: 'pending_review', columns: [
    col(21, 'status', { ai_business_name: 'Trạng thái đơn', ai_description: 'Trạng thái xử lý' }),
    col(22, 'total', { ai_business_name: 'Tổng tiền' }),
  ] },
  { table_id: 12, table_name: 'customers', business_name: 'Khách hàng', description: '', review_status: 'approved', columns: [] },
] };
// getByRole skips hidden elements, so this only finds the detail panel currently shown.
const detail = (label: string) => screen.getByRole('region', { name: label });

it('approves duplicate names by stable table ID with qualified labels', async () => {
  vi.mocked(getSchemaReviewApi).mockResolvedValue({ ...emptyReview, pending_tables: 2, tables: [
    { table_id: 11, table_name: 'orders', physical_schema: 'public', business_name: 'Live', description: '', review_status: 'pending_review', columns: [] },
    { table_id: 12, table_name: 'orders', physical_schema: 'archive', business_name: 'Old', description: '', review_status: 'pending_review', columns: [] },
  ] });
  render(<SchemaReviewView dbId={7} canManageSchema canApproveSchema />);
  fireEvent.click(await screen.findByRole('button', { name: /archive\.orders/ }));
  expect(within(detail('archive.orders')).getByText('Table ID: 12')).toBeVisible();
  expect(screen.queryByRole('region', { name: 'public.orders' })).not.toBeInTheDocument();
  fireEvent.click(within(detail('archive.orders')).getByRole('button', { name: 'Duyệt bảng này' }));
  await waitFor(() => expect(approveSchemaReviewApi).toHaveBeenCalledWith('7', undefined, [12]));
});

it('saves every edited table and column in one batch request', async () => {
  vi.mocked(getSchemaReviewApi).mockResolvedValue(twoTables);
  vi.mocked(saveSchemaReviewBatchApi).mockResolvedValue({ db_id: 7, updated_tables: 1, updated_columns: 1 });
  render(<SchemaReviewView dbId={7} canManageSchema />);
  fireEvent.change(await screen.findByDisplayValue('Đơn hàng'), { target: { value: 'Đơn đặt hàng' } });
  fireEvent.change(screen.getByDisplayValue('total'), { target: { value: 'Tổng giá trị' } });
  fireEvent.click(screen.getByRole('button', { name: 'Lưu tất cả (2)' }));
  await waitFor(() => expect(saveSchemaReviewBatchApi).toHaveBeenCalledWith('7', {
    tables: [{ table_id: 11, business_name: 'Đơn đặt hàng', description: '' }],
    columns: [{ column_id: 22, business_name: 'Tổng giá trị', description: '' }],
  }));
});

it('keeps drafts and shows the error when the batch save fails', async () => {
  vi.mocked(getSchemaReviewApi).mockResolvedValue(twoTables);
  vi.mocked(saveSchemaReviewBatchApi).mockRejectedValue(new Error('Some tables or columns were not found'));
  render(<SchemaReviewView dbId={7} canManageSchema />);
  fireEvent.change(await screen.findByDisplayValue('Đơn hàng'), { target: { value: 'Bản nháp' } });
  fireEvent.click(screen.getByRole('button', { name: 'Lưu tất cả (1)' }));
  expect(await screen.findByText(/were not found/)).toBeVisible();
  expect(screen.getByDisplayValue('Bản nháp')).toBeInTheDocument();
  expect(getSchemaReviewApi).toHaveBeenCalledTimes(1);
});

it('approves the tables ticked in the tree and filters to pending ones', async () => {
  vi.mocked(getSchemaReviewApi).mockResolvedValue(twoTables);
  vi.mocked(approveSchemaReviewApi).mockResolvedValue({ db_id: 7, status: 'approved', approved_tables: 2, approved_columns: 2, pending_tables: 0, pending_columns: 0, pending_relationships: 0 });
  render(<SchemaReviewView dbId={7} canManageSchema canApproveSchema />);
  fireEvent.click(await screen.findByRole('checkbox', { name: 'Chọn tất cả' }));
  fireEvent.click(screen.getByRole('button', { name: 'Duyệt 2 bảng đã chọn' }));
  await waitFor(() => expect(approveSchemaReviewApi).toHaveBeenCalledWith('7', undefined, [11, 12]));
  fireEvent.click(screen.getByRole('checkbox', { name: 'Chỉ chờ review' }));
  const tree = screen.getByRole('navigation', { name: 'Danh sách bảng' });
  expect(within(tree).queryByRole('button', { name: /customers/ })).not.toBeInTheDocument();
  expect(within(tree).getByRole('button', { name: /orders/ })).toBeVisible();
});

it('fills AI proposals into drafts only for the ticked columns', async () => {
  vi.mocked(getSchemaReviewApi).mockResolvedValue(twoTables);
  render(<SchemaReviewView dbId={7} canManageSchema />);
  fireEvent.click(await screen.findByRole('checkbox', { name: 'Chọn cột status' }));
  fireEvent.click(screen.getByRole('button', { name: 'Chấp nhận AI cho 1 cột' }));
  expect(screen.getByDisplayValue('Trạng thái đơn')).toBeInTheDocument();
  expect(screen.getByDisplayValue('Trạng thái xử lý')).toBeInTheDocument();
  expect(screen.getByDisplayValue('total')).toBeInTheDocument();
  expect(saveSchemaReviewBatchApi).not.toHaveBeenCalled();
});

it('opens the DB overview first while it has no description, then switches from the tree', async () => {
  overviewMock.described = false;
  vi.mocked(getSchemaReviewApi).mockResolvedValue(twoTables);
  render(<SchemaReviewView dbId={7} canManageSchema database={{ id: '7', name: 'ecommerce_prod', engine: 'postgresql', status: 'connected', tables: 2 }} />);
  expect(await screen.findByRole('region', { name: 'Tổng quan database' })).toBeInTheDocument();
  expect(screen.queryByRole('region', { name: 'orders' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /orders/ }));
  expect(detail('orders')).toBeVisible();
  expect(screen.queryByRole('region', { name: 'Tổng quan database' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /ecommerce_prod/ }));
  expect(screen.getByRole('region', { name: 'Tổng quan database' })).toBeInTheDocument();
});

it('opens the first pending table when the DB already has a description', async () => {
  overviewMock.described = true;
  vi.mocked(getSchemaReviewApi).mockResolvedValue(twoTables);
  render(<SchemaReviewView dbId={7} canManageSchema />);
  expect(await screen.findByRole('region', { name: 'orders' })).toBeVisible();
  expect(screen.queryByRole('region', { name: 'Tổng quan database' })).not.toBeInTheDocument();
});

it('shows values under the column without the raw allowed-values editor', async () => {
  vi.mocked(getSchemaReviewApi).mockResolvedValue({ ...emptyReview, pending_columns: 1, tables: [
    { table_id: 11, table_name: 'orders', business_name: 'Orders', description: '', review_status: 'approved', columns: [col(21, 'status', { allowed_values: ['completed', 'cancelled'] })] },
  ] });
  render(<SchemaReviewView dbId={7} canManageSchema />);
  expect(await screen.findByText('Column ID: 21')).toBeVisible();
  expect(screen.getByRole('tablist').parentElement).toContainElement(screen.getByRole('button', { name: 'Nạp giá trị nghiệp vụ' }));
  expect(screen.getByRole('button', { name: /Giá trị nghiệp vụ/ })).toBeInTheDocument();
  expect(screen.queryByRole('textbox', { name: 'Giá trị cho phép (JSON array)' })).not.toBeInTheDocument();
});

it('keeps a value draft when switching tables or the review tab', async () => {
  vi.mocked(getSchemaReviewApi).mockResolvedValue(twoTables);
  vi.mocked(getColumnValueMappingsApi).mockResolvedValue({ column_id: 21, complete: false, version: 'v1', items: [
    { db_value: 'paid', business_value: 'Đã trả', source: 'manual', status: 'pending' },
  ] });
  render(<SchemaReviewView dbId={7} canManageSchema canApproveSchema />);
  await screen.findByText('Column ID: 21');
  fireEvent.click(within(detail('orders')).getAllByRole('button', { name: /Giá trị nghiệp vụ/ })[0]);
  fireEvent.change(await screen.findByRole('textbox', { name: /Ý nghĩa nghiệp vụ 1/ }), { target: { value: 'Bản nháp' } });
  fireEvent.click(screen.getByRole('button', { name: /customers/ }));
  fireEvent.click(screen.getByRole('tab', { name: 'Liên kết' }));
  fireEvent.click(screen.getByRole('tab', { name: 'Bảng & cột' }));
  fireEvent.click(screen.getByRole('button', { name: /orders/ }));
  expect(screen.getByRole('textbox', { name: /Ý nghĩa nghiệp vụ 1/ })).toHaveValue('Bản nháp');
});

it('shows the AI description button only for schema managers and dispatches on click', async () => {
  vi.mocked(getSchemaReviewApi).mockResolvedValue(emptyReview);
  vi.mocked(getEnrichStatusApi).mockResolvedValue(idleStatus);
  vi.mocked(generateDescriptionsApi).mockResolvedValue({ db_id: 7, status: 'started' });

  const { unmount } = render(<SchemaReviewView dbId={7} />);
  expect(screen.queryByRole('button', { name: 'Tạo mô tả AI' })).not.toBeInTheDocument();
  unmount();

  render(<SchemaReviewView dbId={7} canManageSchema />);
  fireEvent.click(await screen.findByRole('button', { name: 'Tạo mô tả AI' }));
  await waitFor(() => expect(generateDescriptionsApi).toHaveBeenCalledWith('7'));
});

it('polls enrichment progress and refetches the review when tables complete', async () => {
  vi.mocked(getSchemaReviewApi).mockResolvedValue(emptyReview);
  vi.mocked(getEnrichStatusApi)
    .mockResolvedValueOnce(runningStatus)
    .mockResolvedValueOnce(succeededStatus)
    .mockResolvedValue(idleStatus);

  render(<SchemaReviewView dbId={7} canManageSchema />);
  expect(await screen.findByText(/5\/10/)).toBeInTheDocument();
  // mount load + completed-tables bump + succeeded refresh
  await waitFor(() => expect(getSchemaReviewApi).toHaveBeenCalledTimes(3), { timeout: 4000 });
}, 10000);

it('keeps unsaved edits when an enrichment run finishes', async () => {
  vi.mocked(getSchemaReviewApi).mockResolvedValue({ db_id: 7, status: 'pending_review', pending_tables: 1, pending_columns: 0, pending_relationships: 0, tables: [
    { table_id: 11, table_name: 'orders', business_name: 'Đơn hàng', description: 'Bảng đơn hàng', review_status: 'pending_review', columns: [] },
  ] });
  vi.mocked(getEnrichStatusApi)
    .mockResolvedValueOnce(runningStatus)
    .mockResolvedValueOnce(succeededStatus)
    .mockResolvedValue(idleStatus);

  render(<SchemaReviewView dbId={7} canManageSchema />);
  const nameInput = await screen.findByDisplayValue('Đơn hàng');
  await waitFor(() => expect(getSchemaReviewApi).toHaveBeenCalledTimes(2), { timeout: 4000 });
  fireEvent.change(nameInput, { target: { value: 'Bản nháp chưa lưu' } });
  await screen.findByText(/Đã tạo mô tả xong/, {}, { timeout: 4000 });
  expect(getSchemaReviewApi).toHaveBeenCalledTimes(2);
  expect((nameInput as HTMLInputElement).value).toBe('Bản nháp chưa lưu');
}, 15000);

it('shows failure and retries the enrichment run', async () => {
  vi.mocked(getSchemaReviewApi).mockResolvedValue(emptyReview);
  vi.mocked(getEnrichStatusApi).mockResolvedValue(failedStatus);
  vi.mocked(generateDescriptionsApi).mockResolvedValue({ db_id: 7, status: 'started' });

  render(<SchemaReviewView dbId={7} canManageSchema />);
  expect(await screen.findByText(/LLM down/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Thử lại' }));
  await waitFor(() => expect(generateDescriptionsApi).toHaveBeenCalledTimes(1));
});

it('refetches the review after a failed run so committed tables appear', async () => {
  vi.mocked(getSchemaReviewApi).mockResolvedValue(emptyReview);
  vi.mocked(getEnrichStatusApi)
    .mockResolvedValueOnce(failedStatus)
    .mockResolvedValue(idleStatus);

  render(<SchemaReviewView dbId={7} canManageSchema />);
  expect(await screen.findByText(/LLM down/)).toBeInTheDocument();
  // mount load + failed-run refresh: tables saved before the failure become visible.
  await waitFor(() => expect(getSchemaReviewApi).toHaveBeenCalledTimes(2), { timeout: 4000 });
}, 10000);

it('marks tables and columns with values awaiting review', async () => {
  vi.mocked(getSchemaReviewApi).mockResolvedValue({ ...emptyReview, tables: [{ table_id: 11, table_name: 'orders', business_name: 'Orders', description: '', review_status: 'approved', columns: [{ column_id: 21, column_name: 'status', business_name: 'Status', description: '', data_type: 'TEXT', review_status: 'approved', is_primary_key: false, is_time_dimension: false, pending_value_count: 2 }] }] });
  render(<SchemaReviewView dbId={7} canManageSchema />);
  expect(await screen.findByText(/2 giá trị chờ duyệt/)).toBeVisible();
  expect(screen.getByRole('button', { name: /orders/ })).toHaveTextContent('2');
});

it('hides the AI description button outside the tables tab', async () => {
  vi.mocked(getSchemaReviewApi).mockResolvedValue(emptyReview);
  vi.mocked(getEnrichStatusApi).mockResolvedValue(idleStatus);

  render(<SchemaReviewView dbId={7} canManageSchema />);
  expect(await screen.findByRole('button', { name: 'Tạo mô tả AI' })).toBeInTheDocument();

  fireEvent.click(screen.getByRole('tab', { name: 'Liên kết' }));
  expect(screen.queryByRole('button', { name: 'Tạo mô tả AI' })).not.toBeInTheDocument();
});
