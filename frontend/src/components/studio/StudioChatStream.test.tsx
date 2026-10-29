import { reviewedSuggestionFields } from '@/test/metricReviewFixture';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { metricRequestKey, StudioChatStream } from '@/components/studio/StudioChatStream';

const metricPromptSuggestions = [{
  id: 'net-sales',
  title: 'Tạo metric doanh thu thuần',
  prompt: 'Đề xuất metric doanh thu thuần: xác định bảng gốc, cột tiền, trạng thái giao dịch được tính và cách trừ giảm giá, hoàn tiền. Nêu rõ các giả định chưa xác nhận từ schema.',
}];

describe('StudioChatStream', () => {
  beforeEach(() => {
    cleanup();
  });

  it('renders only the backend metric prompts instead of canned or table-derived prompts', () => {
    const props = {
      messages: [],
      onSendMessage: vi.fn(),
      isLoading: false,
      tableNames: ['orders', 'products'],
      mode: 'metric_studio' as const,
      metricPromptSuggestions: [
        { id: 'net-sales', title: 'Doanh thu lũy kế', prompt: 'Tính doanh thu lũy kế', icon: '📈' },
      ],
    };
    const { rerender } = render(<StudioChatStream {...props} />);

    expect(screen.getByRole('button', { name: /Doanh thu lũy kế/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Tạo metric doanh thu thuần|Tỷ lệ hủy đơn hàng|Số lượng sản phẩm bán/ })).not.toBeInTheDocument();

    rerender(<StudioChatStream {...props} metricPromptSuggestions={[]} />);
    expect(screen.queryByRole('button', { name: /Doanh thu lũy kế/ })).not.toBeInTheDocument();
  });

  it('keeps the existing Data Assistant prompt chips', () => {
    render(
      <StudioChatStream messages={[]} onSendMessage={vi.fn()} isLoading={false} tableNames={[]}
        mode="data_assistant" metricPromptSuggestions={[]} />,
    );

    expect(screen.getByRole('button', { name: /Doanh thu theo khách hàng/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Tìm metric doanh thu đã duyệt/ })).toBeInTheDocument();
  });

  it('opens loaded conversation history at the newest message without scrolling from the top', () => {
    const props = { onSendMessage: vi.fn(), isLoading: false, tableNames: [] };
    const { container, rerender } = render(<StudioChatStream {...props} conversationKey="session-1" messages={[]} />);
    const pane = container.querySelector('.overscroll-contain') as HTMLDivElement;
    Object.defineProperty(pane, 'scrollHeight', { configurable: true, value: 600 });
    pane.scrollTop = 0;

    rerender(<StudioChatStream {...props} conversationKey="session-1" messages={[
      { id: 'old', sender: 'user', text: 'Câu hỏi cũ', timestamp: '10:00' },
      { id: 'latest', sender: 'assistant', text: 'Câu trả lời mới nhất', timestamp: '10:01' },
    ]} />);

    expect(pane.scrollTop).toBe(600);
  });

  it('shows used column names and keeps the proposal text inside its definition card', () => {
    render(
      <StudioChatStream
        messages={[
          {
            id: '1',
            sender: 'assistant',
            text: 'Đã đề xuất 1 Metric Definition.',
            timestamp: '10:00',
            suggestions: [
              { ...reviewedSuggestionFields,
                definition: {
                  metric: {
                    name: 'Doanh thu',
                    formula: { function: 'SUM', expression: 'quantity * unit_price' },
                    base_entity: 'OrderItem',
                    filters: [],
                    status: 'pending_approval',
                    confidence: 'high',
                    excluded_notes: '',
                  },
                },
                yaml_preview: 'metric:\n  name: Doanh thu\n',
              },
            ],
          },
        ]}
        onSendMessage={vi.fn()}
        isLoading={false}
        tableNames={[]}
      />
    );
    // Visual properties check
    expect(screen.getByText(/Công thức tính/i)).toBeInTheDocument();
    expect(screen.getByText(/Dựa vào bảng gốc/i)).toBeInTheDocument();
    expect(screen.getByText(/Cột dữ liệu sử dụng/i)).toBeInTheDocument();
    expect(screen.getByText(/Bộ lọc điều kiện/i)).toBeInTheDocument();
    expect(screen.getByTestId('metric-properties-grid')).toHaveClass('sm:grid-cols-2');
    expect(screen.getByTestId('metric-properties-grid').children).toHaveLength(4);
    const columnSection = screen.getByText(/Cột dữ liệu sử dụng/i).parentElement;
    expect(columnSection).toHaveTextContent('quantity');
    expect(columnSection).toHaveTextContent('unit_price');
    expect(columnSection).not.toHaveTextContent('SUM');
    expect(screen.getAllByText('Đã đề xuất 1 Metric Definition.')).toHaveLength(1);

    // YAML preview is only shown when requested, not as another status line.
    expect(screen.queryByText(/YAML preview sẵn sàng/i)).not.toBeInTheDocument();
    const toggleYamlBtn = screen.getByRole('button', { name: /Hiển thị mã YAML/i });
    fireEvent.click(toggleYamlBtn);
    expect(screen.getByText(/name: Doanh thu/)).toBeInTheDocument();
    expect(screen.queryByText(/SQL Compiled/)).not.toBeInTheDocument();
  });

  it('groups passing and blocked variants together under their curated family', () => {
    render(
      <StudioChatStream
        messages={[{
          id: 'family', sender: 'assistant', text: 'Net sales variants', timestamp: '10:00',
          suggestions: [{
            ...reviewedSuggestionFields,
            candidate_id: 'candidate-pass', group_id: 'net_sales', group_name: 'Doanh số thuần',
            definition: {
              metric: {
                name: 'Doanh thu trước thuế', formula: { function: 'SUM', expression: 'amount' },
                base_entity: 'orders', filters: [], status: 'pending_approval', confidence: 'high',
              },
            } as never,
            yaml_preview: '',
          }],
          blockedCandidates: [{
            name: 'Doanh thu sau thuế', candidate_id: 'candidate-blocked', group_id: 'net_sales',
            group_name: 'Doanh số thuần',
            review: { ...reviewedSuggestionFields.review!, status: 'needs_clarification', summary: 'Thiếu cột VAT' },
          }],
        }]}
        onSendMessage={vi.fn()}
        isLoading={false}
        tableNames={[]}
      />,
    );
    const family = screen.getByRole('heading', { name: 'Doanh số thuần' }).closest('section');
    expect(family).toContainElement(screen.getByText('Doanh thu trước thuế'));
    expect(family).toContainElement(screen.getByText('Doanh thu sau thuế'));
  });

  it('tracks saved state by proposal id when candidate names match', async () => {
    const addMetric = vi.fn().mockResolvedValue(undefined);
    const suggestion = {
      ...reviewedSuggestionFields,
      definition: {
        metric: {
          name: 'Same name', formula: { function: 'SUM', expression: 'amount' },
          base_entity: 'orders', filters: [], status: 'pending_approval', confidence: 'high',
        },
      } as never,
      yaml_preview: '',
    };
    render(
      <StudioChatStream
        messages={[{
          id: 'same-name', sender: 'assistant', text: 'Two variants', timestamp: '10:00', suggestionAction: 'save_metric',
          suggestions: [
            { ...suggestion, proposal_id: 'proposal-first', candidate_id: 'candidate-first' },
            { ...suggestion, proposal_id: 'proposal-second', candidate_id: 'candidate-second' },
          ],
        }]}
        onSendMessage={vi.fn()}
        onAddMetric={addMetric}
        isLoading={false}
        tableNames={[]}
      />,
    );
    fireEvent.click(screen.getAllByRole('button', { name: 'Lưu vào Semantic Layer' })[0]);
    await waitFor(() => expect(screen.getAllByRole('button', { name: 'Đã lưu — mở catalog' })).toHaveLength(1));
    expect(screen.getAllByRole('button', { name: 'Lưu vào Semantic Layer' })).toHaveLength(1);
  });

  it('shows unresolved business assumptions on a low-confidence proposal', () => {
    render(
      <StudioChatStream
        messages={[{
          id: 'assumption', sender: 'assistant', text: 'Gợi ý', timestamp: '10:00',
          suggestions: [{ ...reviewedSuggestionFields, definition: { metric: { name: 'Doanh thu', formula: { function: 'SUM', expression: 'amount' }, base_entity: 'orders', filters: [], status: 'pending_approval', confidence: 'low', excluded_notes: 'Giả định cần xác nhận: Chưa nêu cách xử lý hoàn tiền' } }, yaml_preview: '' }],
        }]}
        onSendMessage={vi.fn()}
        isLoading={false}
        tableNames={[]}
      />,
    );

    expect(screen.getByText('Giả định cần xác nhận', { exact: true })).toBeInTheDocument();
    expect(screen.getByText(/Chưa nêu cách xử lý hoàn tiền/i)).toBeInTheDocument();
  });

  it('renders assistant Markdown with lists, inline code, and GFM tables', () => {
    render(
      <StudioChatStream
        messages={[
          {
            id: 'markdown',
            sender: 'assistant',
            text: '**Metric doanh thu**\n\n- Chọn `revenue`\n- Nhóm theo `created_at`\n\n| Metric | Dimension |\n| --- | --- |\n| Revenue | Month |',
            timestamp: '10:00',
          },
        ]}
        onSendMessage={vi.fn()}
        isLoading={false}
        tableNames={[]}
      />,
    );

    expect(screen.getByText('Metric doanh thu')).toBeInTheDocument();
    expect(screen.getByText('revenue')).toHaveClass('text-primary');
    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(screen.getByText('Month')).toBeInTheDocument();
  });

  it('renders assistant message with icon container and AI agent label', () => {
    render(
      <StudioChatStream
        messages={[
          {
            id: '1',
            sender: 'assistant',
            text: 'Tôi đã phân tích schema',
            timestamp: '10:00',
          },
        ]}
        onSendMessage={vi.fn()}
        isLoading={false}
        tableNames={[]}
      />
    );
    // Assistant message should have AI agent label
    expect(screen.getByText('AI Semantic Agent')).toBeInTheDocument();
    expect(screen.getByText('Tôi đã phân tích schema')).toBeInTheDocument();
  });

  it('shows read-only permission notice in Data Assistant mode', () => {
    render(
      <StudioChatStream
        messages={[]}
        onSendMessage={vi.fn()}
        isLoading={false}
        tableNames={[]}
        mode="data_assistant"
      />,
    );

    expect(screen.getByRole('status')).toHaveTextContent(/không có quyền tạo, sửa hoặc lưu metric/i);
    expect(screen.getByTestId('prompt-suggestion-strip')).toBeInTheDocument();
    expect(screen.getByText('Tìm metric doanh thu đã duyệt')).toBeInTheDocument();
  });

  it('lets a Member submit a generated metric request instead of saving it', () => {
    const submit = vi.fn().mockResolvedValue(undefined);
    render(
      <StudioChatStream
        messages={[{
          id: 'assistant-message', sender: 'assistant', text: 'Gợi ý', timestamp: '10:00',
          suggestionAction: 'submit_metric_request',
          suggestions: [{ ...reviewedSuggestionFields, definition: { metric: { name: 'Doanh thu trước thuế', formula: { function: 'SUM', expression: 'amount' }, base_entity: 'orders', filters: [], status: 'pending_approval', confidence: 'high', excluded_notes: '' } }, yaml_preview: '' }],
        }]}
        onSendMessage={vi.fn()}
        onSubmitMetricRequest={submit}
        isLoading={false}
        tableNames={[]}
        mode="data_assistant"
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /Gửi Data Lead xem xét/i }));
    expect(submit).toHaveBeenCalledWith('assistant-message', 0);
    expect(screen.queryByRole('button', { name: /Lưu vào Semantic Layer/i })).not.toBeInTheDocument();
  });

  it('shows a disabled sent button once the request is pending review', () => {
    render(
      <StudioChatStream
        messages={[{
          id: 'assistant-message', sender: 'assistant', text: 'Gợi ý', timestamp: '10:00',
          suggestionAction: 'submit_metric_request',
          suggestions: [{ ...reviewedSuggestionFields, definition: { metric: { name: 'Doanh thu trước thuế', formula: { function: 'SUM', expression: 'amount' }, base_entity: 'orders', filters: [], status: 'pending_approval', confidence: 'high', excluded_notes: '' } }, yaml_preview: '' }],
        }]}
        onSendMessage={vi.fn()}
        isLoading={false}
        tableNames={[]}
        mode="data_assistant"
        submittedRequestKeys={new Set([metricRequestKey('assistant-message', 0, reviewedSuggestionFields.proposal_id)])}
      />,
    );

    const sentBtn = screen.getByRole('button', { name: /Đã gửi cho Data Lead/i });
    expect(sentBtn).toBeDisabled();
    expect(screen.queryByRole('button', { name: /Gửi Data Lead xem xét/i })).not.toBeInTheDocument();
  });

  it('shows the approved state instead of a resubmit button once the Data Lead approved', () => {
    render(
      <StudioChatStream
        messages={[{
          id: 'assistant-message', sender: 'assistant', text: 'Gợi ý', timestamp: '10:00',
          suggestionAction: 'submit_metric_request',
          suggestions: [{ ...reviewedSuggestionFields, definition: { metric: { name: 'Doanh thu trước thuế', formula: { function: 'SUM', expression: 'amount' }, base_entity: 'orders', filters: [], status: 'pending_approval', confidence: 'high', excluded_notes: '' } }, yaml_preview: '' }],
        }]}
        onSendMessage={vi.fn()}
        isLoading={false}
        tableNames={[]}
        mode="data_assistant"
        approvedRequestKeys={new Set([metricRequestKey('assistant-message', 0, reviewedSuggestionFields.proposal_id)])}
      />,
    );

    const approvedBtn = screen.getByRole('button', { name: /Đã được Data Lead duyệt/i });
    expect(approvedBtn).toBeDisabled();
    expect(screen.queryByRole('button', { name: /Gửi Data Lead xem xét/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Đã gửi cho Data Lead/i })).not.toBeInTheDocument();
  });

  it('ignores a second click while the request is still being sent', () => {
    let resolveSubmit: (() => void) | undefined;
    const submit = vi.fn(
      () => new Promise<void>((resolve) => { resolveSubmit = resolve; }),
    );
    render(
      <StudioChatStream
        messages={[{
          id: 'assistant-message', sender: 'assistant', text: 'Gợi ý', timestamp: '10:00',
          suggestionAction: 'submit_metric_request',
          suggestions: [{ ...reviewedSuggestionFields, definition: { metric: { name: 'Doanh thu trước thuế', formula: { function: 'SUM', expression: 'amount' }, base_entity: 'orders', filters: [], status: 'pending_approval', confidence: 'high', excluded_notes: '' } }, yaml_preview: '' }],
        }]}
        onSendMessage={vi.fn()}
        onSubmitMetricRequest={submit}
        isLoading={false}
        tableNames={[]}
        mode="data_assistant"
      />,
    );

    const sendBtn = screen.getByRole('button', { name: /Gửi Data Lead xem xét/i });
    fireEvent.click(sendBtn);
    fireEvent.click(sendBtn);
    expect(submit).toHaveBeenCalledTimes(1);
    resolveSubmit?.();
  });

  it('renders user message with user label', () => {
    render(
      <StudioChatStream
        messages={[
          {
            id: '1',
            sender: 'user',
            text: 'Tạo metric doanh thu',
            timestamp: '09:55',
          },
        ]}
        onSendMessage={vi.fn()}
        isLoading={false}
        tableNames={[]}
      />
    );
    expect(screen.getByText('Bạn')).toBeInTheDocument();
    expect(screen.getByText('Tạo metric doanh thu')).toBeInTheDocument();
  });

  it('renders suggestion card with metric header, status badge, and YAML toggle', () => {
    render(
      <StudioChatStream
        messages={[
          {
            id: '1',
            sender: 'assistant',
            text: 'Gợi ý',
            timestamp: '10:00',
            suggestions: [
              { ...reviewedSuggestionFields,
                definition: {
                  metric: {
                    name: 'Doanh thu thuần',
                    formula: { function: 'SUM', expression: 'price' },
                    base_entity: 'orders',
                    filters: [],
                    status: 'pending_approval',
                    confidence: 'high',
                    excluded_notes: '',
                  },
                },
                yaml_preview: 'metric:\n  name: Doanh thu thuần\n',
              },
            ],
          },
        ]}
        onSendMessage={vi.fn()}
        isLoading={false}
        tableNames={[]}
      />
    );
    // Metric name heading
    expect(screen.getByText('Doanh thu thuần')).toBeInTheDocument();
    // Status badge
    expect(screen.getByText(/Chờ duyệt/)).toBeInTheDocument();
    // Confidence badge
    expect(screen.getByText(/Độ tin cậy: Cao/)).toBeInTheDocument();
    // YAML toggle button
    expect(screen.getByRole('button', { name: /Hiển thị mã YAML/i })).toBeInTheDocument();
    // Save button
    expect(screen.getByText(/Lưu vào Semantic Layer/)).toBeInTheDocument();
  });

  it('shows saved state after clicking save button', async () => {
    const onAddMetric = vi.fn().mockResolvedValue(undefined);
    render(
      <StudioChatStream
        messages={[
          {
            id: '1',
            sender: 'assistant',
            text: 'Gợi ý',
            timestamp: '10:00',
            suggestions: [
              { ...reviewedSuggestionFields,
                definition: {
                  metric: {
                    name: 'Doanh thu thuần',
                    formula: { function: 'SUM', expression: 'price' },
                    base_entity: 'orders',
                    filters: [],
                    status: 'pending_approval',
                    confidence: 'high',
                    excluded_notes: '',
                  },
                },
                yaml_preview: 'metric:\n  name: Doanh thu\n',
              },
            ],
          },
        ]}
        onSendMessage={vi.fn()}
        isLoading={false}
        tableNames={[]}
        onAddMetric={onAddMetric}
      />
    );
    const saveBtn = screen.getByRole('button', { name: /Lưu vào Semantic Layer/ });
    fireEvent.click(saveBtn);
    // Should call onAddMetric
    expect(onAddMetric).toHaveBeenCalled();
  });

  it('warns when the catalog contains a metric with the same name', () => {
    render(
      <StudioChatStream
        messages={[{
          id: 'saved', sender: 'assistant', text: 'Gợi ý', timestamp: '10:00',
          suggestions: [{ ...reviewedSuggestionFields, definition: { metric: { name: 'Doanh thu thuần', formula: { function: 'SUM', expression: 'price' }, base_entity: 'orders', filters: [], status: 'pending_approval', confidence: 'high', excluded_notes: '' } }, yaml_preview: '' }],
        }]}
        onSendMessage={vi.fn()}
        isLoading={false}
        tableNames={[]}
        savedMetricNames={['Doanh thu thuần']}
      />,
    );

    expect(screen.getByText(/Tên này đã có trong catalog/)).toBeInTheDocument();
  });

  it('prefills the input with a suggested prompt when clicked', () => {
    const onSendMessage = vi.fn().mockResolvedValue(undefined);
    render(
      <StudioChatStream
        messages={[]}
        onSendMessage={onSendMessage}
        isLoading={false}
        tableNames={['orders', 'customers']}
        metricPromptSuggestions={metricPromptSuggestions}
      />
    );

    const strip = screen.getByTestId('prompt-suggestion-strip');
    expect(strip).toHaveClass('overflow-x-auto');
    expect(strip).toHaveClass('whitespace-nowrap');
    const suggestionChip = screen.getByText('Tạo metric doanh thu thuần');
    expect(suggestionChip).toBeInTheDocument();
    expect(strip.querySelectorAll('button')).toHaveLength(1);
    expect(strip.closest('.shrink-0')).not.toHaveClass('border-t');
    expect(strip.closest('.shrink-0')?.nextElementSibling).not.toHaveClass('border-t');

    fireEvent.click(suggestionChip);

    const textarea = screen.getByPlaceholderText(/Mô tả chỉ số bạn muốn tạo/i) as HTMLTextAreaElement;
    expect(onSendMessage).not.toHaveBeenCalled();
    expect(textarea.value).toBe(
      'Đề xuất metric doanh thu thuần: xác định bảng gốc, cột tiền, trạng thái giao dịch được tính và cách trừ giảm giá, hoàn tiền. Nêu rõ các giả định chưa xác nhận từ schema.',
    );
  });

  it('prefills the input when a click has slight pointer movement', () => {
    render(
      <StudioChatStream
        messages={[]}
        onSendMessage={vi.fn()}
        isLoading={false}
        tableNames={['orders']}
        metricPromptSuggestions={metricPromptSuggestions}
      />,
    );

    const strip = screen.getByTestId('prompt-suggestion-strip');
    fireEvent.pointerDown(strip, { pointerId: 1, clientX: 100, isPrimary: true });
    fireEvent.pointerMove(strip, { pointerId: 1, clientX: 106, isPrimary: true });
    fireEvent.pointerUp(strip, { pointerId: 1, clientX: 106, isPrimary: true });
    fireEvent.click(screen.getByText('Tạo metric doanh thu thuần'));

    const textarea = screen.getByPlaceholderText(/Mô tả chỉ số bạn muốn tạo/i) as HTMLTextAreaElement;
    expect(textarea.value).toContain('Đề xuất metric doanh thu thuần');
  });

  it('allows selecting a prompt after dragging the suggestion strip', async () => {
    render(
      <StudioChatStream
        messages={[{ id: 'user-1', sender: 'user', text: 'Xin chào', timestamp: '10:00' }]}
        onSendMessage={vi.fn()}
        isLoading={false}
        tableNames={['orders']}
        metricPromptSuggestions={metricPromptSuggestions}
      />
    );

    const strip = screen.getByTestId('prompt-suggestion-strip');
    Object.defineProperty(strip, 'clientWidth', { configurable: true, value: 240 });
    Object.defineProperty(strip, 'scrollWidth', { configurable: true, value: 720 });
    fireEvent.pointerDown(strip, { pointerId: 1, clientX: 200, isPrimary: true });
    fireEvent.pointerMove(strip, { pointerId: 1, clientX: 80, isPrimary: true });
    fireEvent.pointerUp(strip, { pointerId: 1, clientX: 80, isPrimary: true });

    expect(strip.scrollLeft).toBe(120);
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    fireEvent.click(screen.getByText('Tạo metric doanh thu thuần'));

    const textarea = screen.getByPlaceholderText(/Mô tả chỉ số bạn muốn tạo/i) as HTMLTextAreaElement;
    expect(textarea.value).toBe(
      'Đề xuất metric doanh thu thuần: xác định bảng gốc, cột tiền, trạng thái giao dịch được tính và cách trừ giảm giá, hoàn tiền. Nêu rõ các giả định chưa xác nhận từ schema.',
    );
  });

  it('renders formula display with function and expression parts', () => {
    render(
      <StudioChatStream
        messages={[
          {
            id: '1',
            sender: 'assistant',
            text: 'Gợi ý',
            timestamp: '10:00',
            suggestions: [
              { ...reviewedSuggestionFields,
                definition: {
                  metric: {
                    name: 'AOV',
                    formula: { function: 'AVG', expression: 'total_amount' },
                    base_entity: 'orders',
                    filters: [],
                    status: 'pending_approval',
                    confidence: 'medium',
                    excluded_notes: '',
                  },
                },
                yaml_preview: 'metric:\n  name: AOV\n',
              },
            ],
          },
        ]}
        onSendMessage={vi.fn()}
        isLoading={false}
        tableNames={[]}
      />
    );
    // Formula should show function and expression
    expect(screen.getByText('Công thức tính').parentElement).toHaveTextContent('AVG(total_amount)');
  });

  it('renders refine and edit buttons on suggestion cards', () => {
    render(
      <StudioChatStream
        messages={[
          {
            id: '1',
            sender: 'assistant',
            text: 'Gợi ý',
            timestamp: '10:00',
            suggestions: [
              { ...reviewedSuggestionFields,
                definition: {
                  metric: {
                    name: 'Doanh thu',
                    formula: { function: 'SUM', expression: 'price' },
                    base_entity: 'orders',
                    filters: [],
                    status: 'pending_approval',
                    confidence: 'high',
                    excluded_notes: '',
                  },
                },
                yaml_preview: 'metric:\n  name: Doanh thu\n',
              },
            ],
          },
        ]}
        onSendMessage={vi.fn()}
        isLoading={false}
        tableNames={[]}
      />
    );
    // Refine with AI button
    expect(screen.getByRole('button', { name: /Nhờ AI tinh chỉnh/i })).toBeInTheDocument();
    // Edit manually button
    expect(screen.getByRole('button', { name: /Chỉnh sửa thủ công/i })).toBeInTheDocument();
  });

  it('renders semantic query result card when queryResult is present', () => {
    render(
      <StudioChatStream
        messages={[
          {
            id: 'msg-res-1',
            sender: 'assistant',
            text: 'Số liệu doanh thu',
            timestamp: '10:00',
            queryResult: {
              spec: { metric_ids: [1], dimensions: [], filters: [], limit: 100 },
              columns: ['total_revenue'],
              rows: [[50000000]],
              row_count: 1,
              explanation: 'Doanh thu thuần',
              sql: 'SELECT SUM(amount) AS total_revenue FROM orders',
            },
          },
        ]}
        onSendMessage={vi.fn()}
        isLoading={false}
        tableNames={[]}
      />
    );

    expect(screen.getByText('total_revenue')).toBeInTheDocument();
    expect(screen.getByText('50,000,000')).toBeInTheDocument();
    expect(screen.getByText('Doanh thu thuần')).toBeInTheDocument();
  });

  it('renders clarification buttons and triggers onSelectClarification on click', () => {
    const handleSelect = vi.fn();
    render(
      <StudioChatStream
        messages={[
          {
            id: 'msg-clar-1',
            sender: 'assistant',
            text: 'Bạn muốn xem doanh thu theo chiều nào?',
            timestamp: '10:00',
            clarification: {
              prompt: 'Bạn muốn xem theo?',
              options: [
                {
                  id: 'opt_by_customer',
                  label: 'Theo khách hàng',
                  spec: { metric_ids: [1], dimensions: [{ column_id: 10 }] },
                },
                {
                  id: 'opt_by_month',
                  label: 'Theo tháng',
                  spec: { metric_ids: [1], dimensions: [{ column_id: 20 }] },
                },
              ],
            },
          },
        ]}
        onSendMessage={vi.fn()}
        onSelectClarification={handleSelect}
        isLoading={false}
        tableNames={[]}
      />
    );

    expect(screen.getByText(/Theo khách hàng/i)).toBeInTheDocument();
    expect(screen.getByText(/Theo tháng/i)).toBeInTheDocument();

    fireEvent.click(screen.getByText(/Theo khách hàng/i));
    expect(handleSelect).toHaveBeenCalledWith('msg-clar-1', 'opt_by_customer', 'Theo khách hàng');
  });
});
