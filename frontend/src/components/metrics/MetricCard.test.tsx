import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { MetricCard } from './MetricCard';
import { MetricRecord } from '@/lib/api';
import { createMetricDefinition } from '@/lib/metrics';

const metric: MetricRecord = {
  metric_id: 7,
  name: 'Tổng doanh thu từ các đơn hàng đã hoàn tất trong kỳ báo cáo',
  source: 'ai',
  version: 3,
  status: 'pending_approval',
  created_at: '2026-01-01',
  description: 'Mô tả nghiệp vụ đầy đủ của chỉ số.',
  definition: {
    ...createMetricDefinition('orders'),
    metric: {
      ...createMetricDefinition('orders').metric,
      name: 'total_revenue',
      formula: { function: 'SUM', expression: 'total_amount - discount_amount' },
      filters: [{ field: 'status', operator: 'eq', value: 'completed' }],
      excluded_notes: 'Không bao gồm đơn hàng bị hủy.\nGiữ nguyên toàn bộ ghi chú dài khi xem chi tiết.',
    },
  },
};

afterEach(cleanup);

describe('MetricCard compact rows', () => {
  it('expands full notes, description and filters, switches YAML and collapses', () => {
    render(<MetricCard metric={metric} onHistory={vi.fn()} />);
    const row = screen.getByRole('button', { expanded: false });
    expect(screen.queryByText(metric.description!)).not.toBeInTheDocument();
    fireEvent.click(row);
    expect(row).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText(metric.description!)).toBeInTheDocument();
    expect(screen.getByText(/Giữ nguyên toàn bộ ghi chú/)).toHaveClass('whitespace-pre-wrap');
    expect(screen.getByText('status eq "completed"')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'YAML' }));
    expect(screen.getByText('Metric definition (YAML)')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Định nghĩa' }));
    expect(screen.getByText(metric.description!)).toBeInTheDocument();
    fireEvent.click(row);
    expect(screen.queryByText(metric.description!)).not.toBeInTheDocument();
  });

  it('keeps checkbox selection separate from expanding and approval', () => {
    const select = vi.fn();
    const approve = vi.fn();
    render(<MetricCard metric={metric} onHistory={vi.fn()} onToggleSelect={select} onApprove={approve} />);
    fireEvent.click(screen.getByRole('checkbox'));
    expect(select).toHaveBeenCalledExactlyOnceWith(7);
    expect(screen.getByRole('button', { expanded: false })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { expanded: false }));
    fireEvent.click(screen.getByTitle('Phê duyệt chỉ số này'));
    expect(select).toHaveBeenCalledTimes(1);
    expect(approve).toHaveBeenCalledExactlyOnceWith(7);
  });

  it('closes actions after use and supports Escape', () => {
    const history = vi.fn();
    render(<MetricCard metric={metric} onHistory={history} />);
    const trigger = screen.getByLabelText(`Thao tác với ${metric.name}`);
    fireEvent.click(trigger);
    expect(trigger.closest('details')).toHaveAttribute('open');
    fireEvent.click(screen.getByTitle('Xem lịch sử phiên bản'));
    expect(history).toHaveBeenCalledExactlyOnceWith(7);
    expect(trigger.closest('details')).not.toHaveAttribute('open');
    fireEvent.click(trigger);
    fireEvent.keyDown(trigger, { key: 'Escape' });
    expect(trigger.closest('details')).not.toHaveAttribute('open');
    expect(trigger).toHaveFocus();
  });

  it('preserves legacy normalization and permanent delete confirmation', () => {
    const remove = vi.fn();
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(<MetricCard metric={{ ...metric, definition: null, is_deleted: true }} onHistory={vi.fn()} onPermanentDelete={remove} />);
    fireEvent.click(screen.getByRole('button', { expanded: false }));
    expect(screen.getByText('Metric legacy chưa có canonical definition.')).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(`Thao tác với ${metric.name}`));
    fireEvent.click(screen.getByTitle('Xóa vĩnh viễn khỏi hệ thống'));
    expect(remove).not.toHaveBeenCalled();
    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByLabelText(`Thao tác với ${metric.name}`));
    fireEvent.click(screen.getByTitle('Xóa vĩnh viễn khỏi hệ thống'));
    expect(remove).toHaveBeenCalledExactlyOnceWith(7);
    confirm.mockRestore();
  });
});
