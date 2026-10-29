import { reviewedSuggestionFields } from '@/test/metricReviewFixture';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AIStudioView } from './AIStudioView';
import * as api from '@/lib/api';
import { pendingChatKey, storePendingChat } from '@/lib/pendingChat';
import { traceFixture } from '@/test/chatTraceFixture';

type PromptSuggestionsResponse = { items: { id: string; title: string; prompt: string; icon?: string }[] };
const listMetricPromptSuggestionsApi = vi.mocked(
  (api as unknown as {
    listMetricPromptSuggestionsApi: (dbId: string) => Promise<PromptSuggestionsResponse>;
  }).listMetricPromptSuggestionsApi,
);

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    sendChatOrchestratorApi: vi.fn(),
    getChatSessionDetailApi: vi.fn(),
    listMetricRequestsApi: vi.fn().mockResolvedValue([]),
    listMetricPromptSuggestionsApi: vi.fn().mockResolvedValue({ items: [] }),
    createMetricApi: vi.fn(),
    reviewMetricProposalApi: vi.fn(),
  };
});

describe('AIStudioView', () => {
  beforeEach(() => {
    cleanup();
    vi.resetAllMocks();
    vi.mocked(api.listMetricRequestsApi).mockResolvedValue([]);
    listMetricPromptSuggestionsApi.mockResolvedValue({ items: [] });
    sessionStorage.clear();
  });

  const mockLayer: api.SemanticLayerData = {
    id: 'ecom-live',
    db_name: 'ecom_live',
    db_type: 'postgresql',
    status: 'Saved',
    updated_at: '2026-01-01T00:00:00Z',
    source_type: 'live',
    semantic_db_id: 101,
    tables: [{ table_name: 'orders', business_name: 'Đơn hàng', description: '', columns: [] }],
    metrics: [],
  };

  it('loads prompt suggestions for the active semantic database and renders backend prompts', async () => {
    listMetricPromptSuggestionsApi.mockResolvedValue({
      items: [{ id: 'net-sales', title: 'Doanh thu lũy kế', prompt: 'Tính doanh thu lũy kế', icon: '📈' }],
    });

    render(<AIStudioView layer={mockLayer} theme="light" onMetricsChanged={vi.fn()} />);

    expect(listMetricPromptSuggestionsApi).toHaveBeenCalledWith('101');
    const chip = await screen.findByRole('button', { name: /Doanh thu lũy kế/ });
    expect(screen.queryByText('Tạo metric doanh thu thuần')).not.toBeInTheDocument();
    fireEvent.click(chip);
    expect(screen.getByRole('textbox')).toHaveValue('Tính doanh thu lũy kế');
  });

  it('clears prior database prompts immediately and ignores a late response', async () => {
    let resolveFirst!: (response: PromptSuggestionsResponse) => void;
    listMetricPromptSuggestionsApi
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }))
      .mockResolvedValueOnce({ items: [{ id: 'new', title: 'Metric DB mới', prompt: 'Prompt DB mới' }] });
    const { rerender } = render(<AIStudioView layer={mockLayer} theme="light" onMetricsChanged={vi.fn()} />);

    const otherLayer = { ...mockLayer, semantic_db_id: 202 };
    rerender(<AIStudioView layer={otherLayer} theme="light" onMetricsChanged={vi.fn()} />);
    expect(screen.queryByRole('button', { name: /Tạo metric doanh thu thuần/ })).not.toBeInTheDocument();
    expect(await screen.findByRole('button', { name: 'Metric DB mới' })).toBeInTheDocument();

    await act(async () => resolveFirst({
      items: [{ id: 'old', title: 'Metric DB cũ', prompt: 'Prompt DB cũ' }],
    }));
    expect(screen.queryByRole('button', { name: 'Metric DB cũ' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Metric DB mới' })).toBeInTheDocument();
  });

  it('removes loaded prompts immediately while the next database is loading', async () => {
    let resolveNext!: (response: PromptSuggestionsResponse) => void;
    listMetricPromptSuggestionsApi
      .mockResolvedValueOnce({ items: [{ id: 'old', title: 'Old DB prompt', prompt: 'Old prompt text' }] })
      .mockImplementationOnce(() => new Promise((resolve) => { resolveNext = resolve; }));
    const props = { layer: mockLayer, theme: 'light' as const, onMetricsChanged: vi.fn() };
    const { rerender } = render(<AIStudioView {...props} />);
    expect(await screen.findByRole('button', { name: 'Old DB prompt' })).toBeInTheDocument();

    rerender(<AIStudioView {...props} layer={{ ...mockLayer, semantic_db_id: 202 }} />);

    expect(screen.queryByRole('button', { name: 'Old DB prompt' })).not.toBeInTheDocument();
    expect(screen.getByRole('textbox')).toBeEnabled();
    await act(async () => resolveNext({ items: [{ id: 'new', title: 'New DB prompt', prompt: 'New prompt text' }] }));
    expect(screen.getByRole('button', { name: 'New DB prompt' })).toBeInTheDocument();
  });

  it('clears metric prompts and shows no canned suggestions in Data Assistant mode', async () => {
    listMetricPromptSuggestionsApi.mockResolvedValue({
      items: [{ id: 'metric', title: 'Metric riêng', prompt: 'Metric prompt' }],
    });
    const props = { layer: mockLayer, theme: 'light' as const, onMetricsChanged: vi.fn() };
    const { rerender } = render(<AIStudioView {...props} />);
    expect(await screen.findByRole('button', { name: 'Metric riêng' })).toBeInTheDocument();

    rerender(<AIStudioView {...props} mode="data_assistant" />);

    expect(screen.queryByRole('button', { name: 'Metric riêng' })).not.toBeInTheDocument();
    expect(listMetricPromptSuggestionsApi).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId('prompt-suggestion-strip')).not.toBeInTheDocument();
  });

  it('ignores a metric suggestions response that arrives after switching modes', async () => {
    let resolveSuggestions!: (response: PromptSuggestionsResponse) => void;
    listMetricPromptSuggestionsApi.mockImplementationOnce(
      () => new Promise((resolve) => { resolveSuggestions = resolve; }),
    );
    const props = { layer: mockLayer, theme: 'light' as const, onMetricsChanged: vi.fn() };
    const { rerender } = render(<AIStudioView {...props} />);
    rerender(<AIStudioView {...props} mode="data_assistant" />);

    await act(async () => resolveSuggestions({
      items: [{ id: 'late', title: 'Metric đến muộn', prompt: 'Prompt đến muộn' }],
    }));

    expect(screen.queryByRole('button', { name: 'Metric đến muộn' })).not.toBeInTheDocument();
    expect(screen.queryByTestId('prompt-suggestion-strip')).not.toBeInTheDocument();
  });

  it.each([
    ['empty', async () => ({ items: [] })],
    ['error', async () => { throw new Error('unavailable'); }],
  ])('keeps chat available without metric chips when suggestions are %s', async (_result, getSuggestions) => {
    listMetricPromptSuggestionsApi.mockImplementation(getSuggestions);

    render(<AIStudioView layer={mockLayer} theme="light" onMetricsChanged={vi.fn()} />);

    await waitFor(() => expect(listMetricPromptSuggestionsApi).toHaveBeenCalledWith('101'));
    expect(screen.queryByRole('button', { name: /Tạo metric doanh thu thuần/ })).not.toBeInTheDocument();
    expect(screen.getByRole('textbox')).toBeEnabled();
  });

  it('sends discovery mode explicitly from the schema discovery button', async () => {
    vi.mocked(api.sendChatOrchestratorApi).mockResolvedValue({ intent: 'metric_query', suggestions: [],
      session_id: 'sess-1', user_message_id: 'u-1', assistant_message_id: 'a-1' });
    render(<AIStudioView layer={mockLayer} theme="light" onMetricsChanged={vi.fn()} />);
    fireEvent.click(within(screen.getByRole('banner')).getByRole('button', { name: 'Đề xuất KPI' }));
    await waitFor(() => expect(api.sendChatOrchestratorApi).toHaveBeenCalled());
    expect(vi.mocked(api.sendChatOrchestratorApi).mock.calls[0][7]).toBe('discovery');
  });

  it('creates a new immutable Member proposal when resolving a name conflict', async () => {
    vi.mocked(api.getChatSessionDetailApi).mockResolvedValue({ id: 'sess-1', db_id: 101, title: 'Metrics',
      created_at: '', updated_at: '', message_count: 1, messages: [{ id: 'a-original', session_id: 'sess-1', sequence_no: 1,
        sender: 'assistant', content: 'Proposal', created_at: '', metadata_json: { suggestion_action: 'submit_metric_request',
          suggestions: [{ ...reviewedSuggestionFields, yaml_preview: '', definition: { metric: { name: 'Sales', base_entity: 'orders',
            formula: { function: 'SUM', expression: 'amount' }, filters: [], status: 'pending_approval', excluded_notes: '' } },
            conflict: { proposed_metric_name: 'Sales', existing_metric_name: 'Sales', existing_metric_id: 7, existing_metric_status: 'approved', suggested_name: 'Sales before tax', clarify_question: 'Đổi tên metric' } }],
        } }],
    });
    vi.mocked(api.sendChatOrchestratorApi).mockResolvedValue({ intent: 'metric_query', suggestions: [],
      session_id: 'sess-1', user_message_id: 'u-2', assistant_message_id: 'a-new' });
    render(<AIStudioView layer={mockLayer} theme="light" mode="data_assistant" activeSessionId="sess-1" onMetricsChanged={vi.fn()} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Đổi tên' }));
    await waitFor(() => expect(api.sendChatOrchestratorApi).toHaveBeenCalled());
    expect(vi.mocked(api.sendChatOrchestratorApi).mock.calls[0][1]).toContain('Sales before tax');
    expect(api.reviewMetricProposalApi).not.toHaveBeenCalled();
  });

  it('keeps Thinking expanded and its graph open when a streamed reply completes', async () => {
    window.matchMedia = vi.fn().mockReturnValue({ matches: false });
    let complete!: (value: api.ChatOrchestratorResponse) => void;
    vi.mocked(api.sendChatOrchestratorApi).mockImplementation((_db, _prompt, _session, _id, _selection, _reuse, progress) => {
      progress!.onTrace(traceFixture);
      return new Promise((resolve) => { complete = resolve; });
    });
    render(<AIStudioView layer={mockLayer} theme="light" onMetricsChanged={vi.fn()} />);
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Trace question' } });
    fireEvent.click(screen.getByRole('button', { name: /Gửi tin nhắn/i }));
    fireEvent.click(await screen.findByRole('button', { name: /Thinking/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Luồng agent' }));
    await act(async () => complete({
      intent: 'chitchat', chat_response: 'Final answer', session_id: 'session-1',
      user_message_id: 'u', assistant_message_id: 'a',
      execution_trace: { ...traceFixture, status: 'completed', elapsed_ms: 4000 },
    }));
    expect(screen.getByRole('button', { name: /Thinking.*Hoàn tất/ })).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('heading', { name: 'Luồng agent' })).toBeInTheDocument();
    expect(screen.getByText('Final answer')).toBeInTheDocument();
  });

  it('resumes the same pending request after a page reload', async () => {
    vi.mocked(api.sendChatOrchestratorApi).mockImplementation(() => new Promise(() => {}));
    const props = { layer: mockLayer, theme: 'light' as const, onMetricsChanged: vi.fn() };
    const first = render(<AIStudioView {...props} />);
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Pending question' } });
    fireEvent.click(screen.getByRole('button', { name: /Gửi tin nhắn/i }));
    await waitFor(() => expect(api.sendChatOrchestratorApi).toHaveBeenCalledTimes(1));
    const originalArgs = vi.mocked(api.sendChatOrchestratorApi).mock.calls[0];
    first.unmount();
    vi.mocked(api.sendChatOrchestratorApi).mockResolvedValueOnce({
      intent: 'chitchat', chat_response: 'Recovered answer', session_id: 'sess-recovered',
      user_message_id: 'u-recovered', assistant_message_id: 'a-recovered',
    });
    render(<AIStudioView {...props} />);
    await waitFor(() => expect(api.sendChatOrchestratorApi).toHaveBeenCalledTimes(2));
    expect(vi.mocked(api.sendChatOrchestratorApi).mock.calls[1].slice(0, 6)).toEqual(originalArgs.slice(0, 6));
    expect(originalArgs[6]?.signal.aborted).toBe(true);
    expect(vi.mocked(api.sendChatOrchestratorApi).mock.calls[1][6]?.signal.aborted).toBe(false);
    expect(await screen.findByText('Recovered answer')).toBeInTheDocument();
    expect(screen.getByText('Pending question')).toBeInTheDocument();
  });

  it.each([false, true])('restores existing history without duplicate messages (completed: %s)', async (completed) => {
    const key = pendingChatKey(101, 'sess-1');
    storePendingChat(key, { prompt: 'Pending question', clientMessageId: 'client-1', sessionId: 'sess-1' });
    const userMessage: api.ChatMessageItem = {
      id: 'user-1', session_id: 'sess-1', sender: 'user', content: 'Pending question', sequence_no: 1,
      client_message_id: 'client-1', created_at: '2026-01-01T00:00:00Z',
    };
    vi.mocked(api.getChatSessionDetailApi).mockResolvedValueOnce({
      id: 'sess-1', db_id: 101, title: 'Chat', message_count: completed ? 2 : 1,
      created_at: userMessage.created_at, updated_at: userMessage.created_at,
      messages: completed ? [userMessage, {
        ...userMessage, id: 'assistant-1', sender: 'assistant', content: 'Recovered answer',
        sequence_no: 2, client_message_id: 'client-1:assistant',
      }] : [userMessage],
    });
    vi.mocked(api.sendChatOrchestratorApi).mockResolvedValueOnce({
      intent: 'chitchat', chat_response: 'Recovered answer', session_id: 'sess-1',
      user_message_id: 'user-1', assistant_message_id: 'assistant-1',
    });
    render(<AIStudioView layer={mockLayer} theme="light" activeSessionId="sess-1" onMetricsChanged={vi.fn()} />);
    expect(await screen.findByText('Recovered answer')).toBeInTheDocument();
    expect(screen.getAllByText('Pending question')).toHaveLength(1);
    expect(api.sendChatOrchestratorApi).toHaveBeenCalledTimes(completed ? 0 : 1);
    expect(sessionStorage.getItem(key)).toBeNull();
  });

  it('renders Data Assistant view header and welcome message for Member', () => {
    render(
      <AIStudioView
        layer={mockLayer}
        theme="light"
        mode="data_assistant"
        onMetricsChanged={vi.fn()}
      />
    );

    expect(screen.getByText('Data Assistant')).toBeInTheDocument();
    expect(screen.getByText(/Hỏi về cấu trúc, chỉ số đã duyệt/i)).toBeInTheDocument();
  });

  it('renders semantic query result table when response has intent semantic_query', async () => {
    vi.mocked(api.sendChatOrchestratorApi).mockResolvedValueOnce({
      intent: 'semantic_query',
      chat_response: 'Doanh thu theo khách hàng',
      semantic_query_result: {
        spec: { metric_ids: [1], dimensions: [{ column_id: 10 }], filters: [], limit: 100 },
        columns: ['customer_name', 'total_revenue'],
        rows: [['Khách hàng Alpha', 5000000]],
        row_count: 1,
        explanation: 'Tính từ metric Doanh thu',
      },
      session_id: 'sess-1',
      user_message_id: 'u-1',
      assistant_message_id: 'a-1',
    });

    render(
      <AIStudioView
        layer={mockLayer}
        theme="light"
        mode="data_assistant"
        onMetricsChanged={vi.fn()}
      />
    );

    const textarea = screen.getByPlaceholderText(/Hỏi về cấu trúc/i);
    fireEvent.change(textarea, { target: { value: 'Tổng doanh thu theo khách hàng' } });
    const sendBtn = screen.getByRole('button', { name: /Gửi tin nhắn/i });
    fireEvent.click(sendBtn);

    await waitFor(() => {
      expect(screen.getByText('Khách hàng Alpha')).toBeInTheDocument();
      expect(screen.getByText('5,000,000')).toBeInTheDocument();
    });
  });

  it.each(['semantic_query', 'data_question', 'metric_query'] as const)('shows clarification options for %s and sends the selection', async (intent) => {
    vi.mocked(api.sendChatOrchestratorApi)
      .mockResolvedValueOnce({
        intent,
        chat_response: 'Vui lòng làm rõ câu hỏi',
        clarification: {
          prompt: 'Bạn muốn xem theo?',
          options: [
            {
              id: 'opt_1',
              label: 'Theo khách hàng',
              spec: { metric_ids: [1], dimensions: [{ column_id: 10 }] },
            },
          ],
        },
        session_id: 'sess-1',
        user_message_id: 'u-1',
        assistant_message_id: 'a-1',
      })
      .mockResolvedValueOnce({
        intent: 'semantic_query',
        chat_response: 'Kết quả theo khách hàng',
        semantic_query_result: {
          spec: { metric_ids: [1], dimensions: [{ column_id: 10 }], filters: [], limit: 100 },
          columns: ['customer_name', 'revenue'],
          rows: [['Alpha', 1000000]],
          row_count: 1,
          explanation: 'Doanh thu khách hàng',
        },
        session_id: 'sess-1',
        user_message_id: 'u-2',
        assistant_message_id: 'a-2',
      });

    render(
      <AIStudioView
        layer={mockLayer}
        theme="light"
        mode="data_assistant"
        onMetricsChanged={vi.fn()}
      />
    );

    const textarea = screen.getByPlaceholderText(/Hỏi về cấu trúc/i);
    fireEvent.change(textarea, { target: { value: 'Doanh thu' } });
    fireEvent.click(screen.getByRole('button', { name: /Gửi tin nhắn/i }));

    await waitFor(() => {
      expect(screen.getByText(/Theo khách hàng/i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: 'Theo khách hàng' }));

    await waitFor(() => {
      expect(api.sendChatOrchestratorApi).toHaveBeenCalledWith(
        '101',
        'Theo khách hàng',
        null,
        expect.any(String),
        { assistant_message_id: 'a-1', option_id: 'opt_1' }, null, expect.objectContaining({ onTrace: expect.any(Function) }), 'requested',
      );
      expect(screen.getByText('Alpha')).toBeInTheDocument();
      expect(screen.getByText('1,000,000')).toBeInTheDocument();
    });
  });

  it('renders generated suggestions after metric clarification selection', async () => {
    vi.mocked(api.sendChatOrchestratorApi)
      .mockResolvedValueOnce({
        intent: 'semantic_query',
        chat_response: 'Chưa có metric phù hợp',
        clarification: {
          prompt: 'Bạn có muốn tạo metric không?',
          options: [
            {
              id: 'create_metric',
              label: 'Tạo Business Metric',
              spec: null,
              action: 'create_metric',
            },
          ],
        },
        session_id: 'sess-1',
        user_message_id: 'u-1',
        assistant_message_id: 'a-1',
      })
      .mockResolvedValueOnce({
        intent: 'metric_query',
        chat_response: null,
        suggestions: [
          { ...reviewedSuggestionFields,
            definition: {
              schema_version: 2,
              metric: {
                name: 'Doanh thu theo chi nhánh',
                formula: { function: 'SUM', expression: 'total_amount' },
                base_entity: 'orders',
                filters: [],
                status: 'unverified',
                confidence: 'medium',
                excluded_notes: '',
              },
            },
            yaml_preview: 'metric: doanh thu theo chi nhánh',
          },
        ],
        suggestion_action: 'submit_metric_request',
        duplicates: [],
        session_id: 'sess-1',
        user_message_id: 'u-2',
        assistant_message_id: 'a-2',
      });

    render(
      <AIStudioView
        layer={mockLayer}
        theme="light"
        mode="data_assistant"
        onMetricsChanged={vi.fn()}
      />
    );

    const textarea = screen.getByPlaceholderText(/Hỏi về cấu trúc/i);
    fireEvent.change(textarea, { target: { value: 'Doanh thu theo chi nhánh' } });
    fireEvent.click(screen.getByRole('button', { name: /Gửi tin nhắn/i }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Tạo Business Metric' })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: 'Tạo Business Metric' }));

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Doanh thu theo chi nhánh' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Gửi Data Lead xem xét' })).toBeInTheDocument();
    });
  });

  it.each([false, true])('calculates an existing metric and preserves its proposal (conflict: %s)', async (conflict) => {
    vi.mocked(api.sendChatOrchestratorApi)
      .mockResolvedValueOnce({
        intent: 'metric_query',
        chat_response: 'Metric này đã tồn tại.',
        suggestions: conflict ? [{
          yaml_preview: 'metric: new_aov',
          definition: { metric: { name: 'New AOV', formula: { function: 'AVG', expression: 'order_total' }, base_entity: 'orders', filters: [], status: 'unverified', excluded_notes: '' } },
          conflict: { proposed_metric_name: 'New AOV', existing_metric_id: 7, existing_metric_name: 'AOV', existing_metric_status: 'approved', suggested_name: 'New AOV 2', clarify_question: 'Name conflict' },
        }] : [],
        duplicates: conflict ? [] : [
          {
            existing_metric_id: 7,
            existing_metric_name: 'AOV',
            existing_metric_status: 'approved',
            user_message: 'Metric AOV đã tồn tại trong hệ thống.',
            similarity_reason: 'Trùng công thức.',
            existing_definition: {
              metric: {
                name: 'AOV',
                formula: { function: 'AVG', expression: 'order_total' },
                base_entity: 'orders',
                filters: [],
                status: 'approved',
                excluded_notes: '',
              },
            },
            existing_yaml: 'metric:\n  name: AOV',
          },
        ],
        session_id: 'sess-1',
        user_message_id: 'u-1',
        assistant_message_id: 'a-1',
      })
      .mockResolvedValueOnce({
        intent: 'semantic_query',
        chat_response: 'Kết quả AOV',
        semantic_query_result: {
          spec: { metric_ids: [7], dimensions: [], filters: [], limit: 100 },
          columns: ['aov'],
          rows: [[250000]],
          row_count: 1,
          explanation: 'Kết quả từ metric AOV',
        },
        session_id: 'sess-1',
        user_message_id: 'u-2',
        assistant_message_id: 'a-2',
      });

    render(
      <AIStudioView
        layer={mockLayer}
        theme="light"
        mode="data_assistant"
        onMetricsChanged={vi.fn()}
      />
    );

    const textarea = screen.getByPlaceholderText(/Hỏi về cấu trúc/i);
    fireEvent.change(textarea, { target: { value: 'AOV' } });
    fireEvent.click(screen.getByRole('button', { name: /Gửi tin nhắn/i }));

    await waitFor(() => expect(screen.getByText(conflict ? 'Name conflict' : 'Metric AOV đã tồn tại trong hệ thống.')).toBeInTheDocument());
    if (!conflict) expect(screen.getByText('Metric có sẵn (YAML)')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Tính kết quả từ chỉ số này/i }));

    await waitFor(() => {
      expect(api.sendChatOrchestratorApi).toHaveBeenLastCalledWith(
        '101',
        'Tính kết quả từ chỉ số "AOV"',
        null,
        expect.any(String),
        null,
        7,
        expect.objectContaining({ onTrace: expect.any(Function) }), 'requested',
      );
      expect(screen.getByText('250,000')).toBeInTheDocument();
      if (conflict) expect(screen.getByRole('heading', { name: 'New AOV' })).toBeInTheDocument();
    });
  });
});
