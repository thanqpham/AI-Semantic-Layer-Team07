import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { MetricRejectDialog } from './MetricRejectDialog';

const makeProps = () => ({
  metricId: 7,
  metricName: 'Tổng doanh thu',
  onClose: vi.fn(),
  onReject: vi.fn().mockResolvedValue(undefined),
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('MetricRejectDialog', () => {
  it('requires a non-blank reason before rejecting', () => {
    const props = makeProps();
    render(<MetricRejectDialog {...props} />);

    fireEvent.click(screen.getByRole('button', { name: /Xác nhận từ chối/ }));

    expect(screen.getByText(/Vui lòng nhập lý do từ chối/)).toBeInTheDocument();
    expect(props.onReject).not.toHaveBeenCalled();
  });

  it('submits the trimmed reason once confirmed', async () => {
    const props = makeProps();
    render(<MetricRejectDialog {...props} />);

    fireEvent.change(screen.getByLabelText(/Lý do từ chối/), {
      target: { value: '  Công thức trùng metric khác  ' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Xác nhận từ chối/ }));

    await waitFor(() =>
      expect(props.onReject).toHaveBeenCalledExactlyOnceWith(7, 'Công thức trùng metric khác'),
    );
    expect(props.onClose).toHaveBeenCalled();
  });

  it('closes without rejecting when cancelled', () => {
    const props = makeProps();
    render(<MetricRejectDialog {...props} />);

    fireEvent.change(screen.getByLabelText(/Lý do từ chối/), {
      target: { value: 'Lý do bất kỳ' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Hủy' }));

    expect(props.onClose).toHaveBeenCalled();
    expect(props.onReject).not.toHaveBeenCalled();
  });

  it('renders custom labels for the delete usage', async () => {
    const props = makeProps();
    render(
      <MetricRejectDialog
        {...props}
        title="Xóa chỉ số"
        hint="Metric bị xóa sẽ chuyển vào Thùng rác và hiển thị lý do trên card đề xuất."
        reasonLabel="Lý do xóa"
        confirmLabel="Xác nhận xóa"
        blankReasonError="⚠️ Vui lòng nhập lý do xóa trước khi bấm Xóa."
      />,
    );

    expect(screen.getByText('Xóa chỉ số')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Xác nhận xóa/ }));

    expect(await screen.findByText(/Vui lòng nhập lý do xóa/)).toBeInTheDocument();
    expect(props.onReject).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText(/Lý do xóa/), { target: { value: 'Không còn dùng' } });
    fireEvent.click(screen.getByRole('button', { name: /Xác nhận xóa/ }));

    await waitFor(() => expect(props.onReject).toHaveBeenCalledExactlyOnceWith(7, 'Không còn dùng'));
  });

  it('surfaces the error and stays open when the reject request fails', async () => {
    const props = makeProps();
    props.onReject = vi.fn().mockRejectedValue(new Error('Metric has no version awaiting approval'));
    render(<MetricRejectDialog {...props} />);

    fireEvent.change(screen.getByLabelText(/Lý do từ chối/), {
      target: { value: 'Trùng công thức' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Xác nhận từ chối/ }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Metric has no version awaiting approval');
    expect(props.onClose).not.toHaveBeenCalled();
  });
});
