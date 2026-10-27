import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';

import { approveSchemaReviewApi, getSchemaReviewApi } from '@/lib/api';
import { SchemaReviewView } from './SchemaReviewView';

vi.mock('@/components/schema-review/RelationshipsPanel', () => ({RelationshipsPanel:()=> <div>Relationship queue</div>}));
vi.mock('@/lib/api', () => ({
  getSchemaReviewApi: vi.fn(),
  approveSchemaReviewApi: vi.fn(),
  updateColumnReviewApi: vi.fn(),
  updateTableReviewApi: vi.fn(),
}));

afterEach(cleanup);

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
 await waitFor(()=>expect(approveSchemaReviewApi).toHaveBeenCalledWith('7',undefined));
 expect(screen.getByText(/liên kết chờ xác nhận riêng/)).toHaveTextContent('3');
});


it('does not advertise or load a read-only review queue without schema permission', () => {
 vi.mocked(getSchemaReviewApi).mockClear();
 render(<SchemaReviewView dbId={7} />);
 expect(screen.getByRole('status')).toHaveTextContent('Schema Review requires schema management permission');
 expect(screen.queryByText('Relationship queue')).not.toBeInTheDocument();
 expect(getSchemaReviewApi).not.toHaveBeenCalled();
});
