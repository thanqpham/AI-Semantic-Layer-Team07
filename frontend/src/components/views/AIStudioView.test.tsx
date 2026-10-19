import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AIStudioView } from './AIStudioView';
import * as api from '@/lib/api';

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    sendChatOrchestratorApi: vi.fn(),
    getChatSessionDetailApi: vi.fn(),
    listMetricRequestsApi: vi.fn().mockResolvedValue([]),
    createMetricApi: vi.fn(),
  };
});

describe('AIStudioView', () => {
  beforeEach(() => {
    cleanup();
    vi.clearAllMocks();
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

  it('renders Data Assistant view header and welcome message for Member', () => {
    render(
      <AIStudioView
        layer={mockLayer}
        theme="light"
        mode="data_assistant"
        onMetricsChanged={vi.fn()}
      />
    );

    expect(screen.getByText('Trợ lý dữ liệu')).toBeInTheDocument();
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

  it('handles clarification selection click by sending option payload', async () => {
    vi.mocked(api.sendChatOrchestratorApi)
      .mockResolvedValueOnce({
        intent: 'semantic_query',
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
        { assistant_message_id: 'a-1', option_id: 'opt_1' }
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
          {
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

  it('calculates an existing duplicate metric with its stable metric id', async () => {
    vi.mocked(api.sendChatOrchestratorApi)
      .mockResolvedValueOnce({
        intent: 'metric_query',
        chat_response: 'Metric này đã tồn tại.',
        duplicates: [
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

    await waitFor(() => expect(screen.getByText('Metric AOV đã tồn tại trong hệ thống.')).toBeInTheDocument());
    expect(screen.getByText('Metric có sẵn (YAML)')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Tính kết quả từ chỉ số này/i }));

    await waitFor(() => {
      expect(api.sendChatOrchestratorApi).toHaveBeenLastCalledWith(
        '101',
        'Tính kết quả từ chỉ số "AOV"',
        null,
        expect.any(String),
        null,
        7,
      );
      expect(screen.getByText('250,000')).toBeInTheDocument();
    });
  });
});
