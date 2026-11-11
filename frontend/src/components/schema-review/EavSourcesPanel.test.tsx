import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

import {
  createEavConfigApi,
  createEavMetricApi,
  listEavConfigsApi,
  reviewEavConfigApi,
  SemanticApiError,
  type EavConfig,
} from '@/lib/api';
import { EavSourcesPanel } from './EavSourcesPanel';

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    listEavConfigsApi: vi.fn(),
    createEavConfigApi: vi.fn(),
    reviewEavConfigApi: vi.fn(),
    createEavMetricApi: vi.fn(),
  };
});

const config = (review_status: EavConfig['review_status']): EavConfig => ({
  id: 3,
  name: 'EAV chính',
  entity_table: 'entity_eav',
  entity_id_column: 'entity_id',
  attribute_mode: 'direct',
  attribute_column: 'attr_code',
  attribute_fk_column: null,
  dict_table: null,
  dict_key_column: null,
  dict_label_column: null,
  value_columns: { number: 'value_num', string: 'value_str' },
  history: null,
  review_status,
  reviewed_by: null,
  reviewed_at: null,
  created_at: '2026-11-11T00:00:00',
  attributes: [
    {
      id: 11,
      attribute_key: 'revenue',
      label: 'Doanh thu',
      description: '',
      data_type: 'number' as const,
      value_column: null,
      multi_value_rule: 'reject' as const,
      history_enabled: false,
    },
    {
      id: 12,
      attribute_key: 'region',
      label: 'Khu vực',
      description: '',
      data_type: 'string' as const,
      value_column: null,
      multi_value_rule: 'reject' as const,
      history_enabled: false,
    },
  ],
});

beforeEach(() => {
  vi.mocked(listEavConfigsApi).mockResolvedValue([config('approved')]);
  vi.mocked(reviewEavConfigApi).mockResolvedValue(config('approved'));
  vi.mocked(createEavMetricApi).mockResolvedValue({ metric_id: 42, name: 'Tổng doanh thu', status: 'draft' });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it('lists configs with attributes and review status', async () => {
  render(<EavSourcesPanel dbId={5} canManageSchema canApproveMetrics />);
  expect(await screen.findByText('EAV chính')).toBeInTheDocument();
  expect(screen.getByText('Doanh thu')).toBeInTheDocument();
  expect(screen.getByText(/approved/)).toBeInTheDocument();
});

it('shows approve and reject actions for pending configs', async () => {
  vi.mocked(listEavConfigsApi).mockResolvedValue([config('pending_review')]);
  render(<EavSourcesPanel dbId={5} canManageSchema canApproveMetrics />);
  expect(await screen.findByRole('button', { name: /duyệt/i })).toBeInTheDocument();
});

it('approves a pending config through the API', async () => {
  vi.mocked(listEavConfigsApi).mockResolvedValue([config('pending_review')]);
  render(<EavSourcesPanel dbId={5} canManageSchema canApproveMetrics />);
  fireEvent.click(await screen.findByRole('button', { name: /duyệt/i }));
  await waitFor(() => expect(reviewEavConfigApi).toHaveBeenCalledWith(5, 3, 'approve'));
});

it('creates a metric from a number attribute', async () => {
  render(<EavSourcesPanel dbId={5} canManageSchema canApproveMetrics />);
  fireEvent.click(await screen.findByRole('button', { name: /tạo metric từ "doanh thu"/i }));
  await waitFor(() => expect(createEavMetricApi).toHaveBeenCalledWith(5, 3, 11, { aggregation: 'SUM' }));
});

it('submits the declaration form with the expected payload', async () => {
  render(<EavSourcesPanel dbId={5} canManageSchema canApproveMetrics />);
  fireEvent.click(await screen.findByRole('button', { name: /khai báo nguồn eav/i }));
  fireEvent.change(screen.getByLabelText(/tên cấu hình/i), { target: { value: 'EAV bán hàng' } });
  fireEvent.change(screen.getByLabelText(/bảng entity/i), { target: { value: 'entity_eav' } });
  fireEvent.change(screen.getByLabelText(/cột định danh thực thể/i), { target: { value: 'entity_id' } });
  fireEvent.change(screen.getByLabelText(/cột mã thuộc tính/i), { target: { value: 'attr_code' } });
  fireEvent.change(screen.getByLabelText(/cột giá trị number/i), { target: { value: 'value_num' } });
  fireEvent.change(screen.getByLabelText(/cột giá trị string/i), { target: { value: 'value_str' } });
  fireEvent.change(screen.getByLabelText(/khóa thuộc tính/i), { target: { value: 'revenue' } });
  fireEvent.change(screen.getByLabelText(/tên hiển thị/i), { target: { value: 'Doanh thu' } });
  fireEvent.click(screen.getByLabelText(/bật history/i));
  fireEvent.click(screen.getByRole('button', { name: /lưu cấu hình/i }));
  await waitFor(() =>
    expect(createEavConfigApi).toHaveBeenCalledWith(5, {
      name: 'EAV bán hàng',
      entity_table: 'entity_eav',
      entity_id_column: 'entity_id',
      attribute_mode: 'direct',
      attribute_column: 'attr_code',
      attribute_fk_column: null,
      dict_table: null,
      dict_key_column: null,
      dict_label_column: null,
      value_columns: { number: 'value_num', string: 'value_str' },
      history: null,
      attributes: [
        {
          attribute_key: 'revenue',
          label: 'Doanh thu',
          data_type: 'number',
          multi_value_rule: 'reject',
          history_enabled: true,
        },
      ],
    }),
  );
});

it('shows backend validation errors in Vietnamese', async () => {
  vi.mocked(createEavConfigApi).mockRejectedValue(
    new SemanticApiError(422, 'Cột "ghost" không tồn tại', ['Cột "ghost" không tồn tại']),
  );
  render(<EavSourcesPanel dbId={5} canManageSchema canApproveMetrics />);
  fireEvent.click(await screen.findByRole('button', { name: /khai báo nguồn eav/i }));
  fireEvent.change(screen.getByLabelText(/tên cấu hình/i), { target: { value: 'EAV bán hàng' } });
  fireEvent.change(screen.getByLabelText(/bảng entity/i), { target: { value: 'entity_eav' } });
  fireEvent.change(screen.getByLabelText(/cột định danh thực thể/i), { target: { value: 'entity_id' } });
  fireEvent.change(screen.getByLabelText(/cột mã thuộc tính/i), { target: { value: 'attr_code' } });
  fireEvent.change(screen.getByLabelText(/cột giá trị number/i), { target: { value: 'value_num' } });
  fireEvent.change(screen.getByLabelText(/khóa thuộc tính/i), { target: { value: 'revenue' } });
  fireEvent.change(screen.getByLabelText(/tên hiển thị/i), { target: { value: 'Doanh thu' } });
  fireEvent.click(screen.getByRole('button', { name: /lưu cấu hình/i }));
  expect(await screen.findByText(/Cột "ghost" không tồn tại/)).toBeInTheDocument();
});

it('hides management actions without permission', async () => {
  render(<EavSourcesPanel dbId={5} canManageSchema={false} canApproveMetrics={false} />);
  await screen.findByText('EAV chính');
  expect(screen.queryByRole('button', { name: /khai báo nguồn eav/i })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /tạo metric/i })).not.toBeInTheDocument();
});
