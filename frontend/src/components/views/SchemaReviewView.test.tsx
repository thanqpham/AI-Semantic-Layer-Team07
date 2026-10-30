import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';

import {
  approveSchemaReviewApi,
  generateDescriptionsApi,
  getEnrichStatusApi,
  getSchemaReviewApi,
  updateColumnReviewApi,
  updateTableReviewApi,
  type EnrichStatus,
  type SchemaReview,
} from '@/lib/api';
import { SchemaReviewView } from './SchemaReviewView';

vi.mock('@/components/schema-review/RelationshipsPanel', () => ({RelationshipsPanel:()=> <div>Relationship queue</div>}));
vi.mock('@/lib/api', () => ({
  getSchemaReviewApi: vi.fn(),
  approveSchemaReviewApi: vi.fn(),
  updateColumnReviewApi: vi.fn(),
  updateTableReviewApi: vi.fn(),
  generateDescriptionsApi: vi.fn(),
  getEnrichStatusApi: vi.fn(),
}));

const idleStatus: EnrichStatus = { db_id: 7, status: 'idle', phase: '', total_tables: 0, completed_tables: 0, current_table: null, error: null, started_at: null, finished_at: null };
const runningStatus: EnrichStatus = { ...idleStatus, status: 'running', phase: 'generating', total_tables: 10, completed_tables: 5, current_table: 'orders' };
const succeededStatus: EnrichStatus = { ...idleStatus, status: 'succeeded' };
const failedStatus: EnrichStatus = { ...idleStatus, status: 'failed', error: 'LLM down' };
const emptyReview: SchemaReview = { db_id: 7, status: 'pending_review', pending_tables: 0, pending_columns: 0, pending_relationships: 0, tables: [] };

afterEach(() => { cleanup(); vi.clearAllMocks(); });

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
 expect(screen.getByText('Relationship queue')).toBeVisible();expect(screen.getByRole('tab',{name:'Bảng & cột'})).toBeInTheDocument();
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

 it('approves duplicate names by stable table ID with qualified labels', async () => {
 vi.mocked(approveSchemaReviewApi).mockClear();
 vi.mocked(getSchemaReviewApi).mockResolvedValue({db_id:7,status:'pending_review',pending_tables:2,pending_columns:0,pending_relationships:0,tables:[
 {table_id:11,table_name:'orders',physical_schema:'public',business_name:'Live',description:'',review_status:'pending_review',columns:[]},
 {table_id:12,table_name:'orders',physical_schema:'archive',business_name:'Old',description:'',review_status:'pending_review',columns:[]},
 ]});
 render(<SchemaReviewView dbId={7} canManageSchema canApproveSchema/>);
 await screen.findByText('public.orders'); expect(screen.getByText('archive.orders')).toBeVisible();
 fireEvent.change(screen.getAllByRole('textbox')[2],{target:{value:'Edited archive'}});
 fireEvent.click(screen.getAllByRole('button').find(button=>button.textContent === 'L\u01b0u' && !button.hasAttribute('disabled'))!);
 await waitFor(()=>expect(updateTableReviewApi).toHaveBeenCalledWith('7','orders','Edited archive','',12));
 const buttons=screen.getAllByRole('button',{name:'Duy\u1ec7t b\u1ea3ng n\u00e0y'}); fireEvent.click(buttons[1]);
 await waitFor(()=>expect(approveSchemaReviewApi).toHaveBeenCalledWith('7',undefined,[12]));
 });

it('saves edited allowed values as JSON metadata', async () => {
 vi.mocked(getSchemaReviewApi).mockResolvedValue({db_id:7,status:'pending_review',pending_tables:0,pending_columns:1,pending_relationships:0,tables:[
  {table_id:11,table_name:'orders',business_name:'Orders',description:'',review_status:'approved',columns:[
   {column_id:21,column_name:'status',business_name:'Status',description:'',data_type:'TEXT',review_status:'pending_review',is_primary_key:false,is_time_dimension:false,allowed_values:['completed','cancelled']},
  ]},
 ]});
 render(<SchemaReviewView dbId={7} canManageSchema/>);
 const values = await screen.findByRole('textbox',{name:'Giá trị cho phép (JSON array)'});
 fireEvent.change(values,{target:{value:'["completed", "returned"]'}});
 fireEvent.click(screen.getAllByRole('button').find(button=>button.textContent === 'Lưu' && !button.hasAttribute('disabled'))!);
 await waitFor(()=>expect(updateColumnReviewApi).toHaveBeenCalledWith('7','orders','status','Status','',11,['completed','returned']));
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
