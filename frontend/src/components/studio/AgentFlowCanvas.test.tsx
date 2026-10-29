import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AgentFlowCanvas } from './AgentFlowCanvas';
import { LanguageProvider } from '@/context/LanguageContext';
import type { ExecutionTrace } from '@/lib/chatTrace';

const mockFitView = vi.fn();

vi.mock('@xyflow/react', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@xyflow/react')>();
  return {
    ...actual,
    useReactFlow: () => {
      const orig = actual.useReactFlow();
      return {
        ...orig,
        fitView: mockFitView,
      };
    },
  };
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function makeTrace(overrides: Partial<ExecutionTrace> = {}): ExecutionTrace {
  return {
    run_id: 'test-run-1',
    status: 'completed',
    started_at: '2026-10-30T00:00:00Z',
    finished_at: '2026-10-30T00:00:10Z',
    elapsed_ms: 10000,
    events: [],
    ...overrides,
  };
}

function renderCanvas(trace: ExecutionTrace, reconnecting = false) {
  return render(
    <LanguageProvider>
      <AgentFlowCanvas trace={trace} reconnecting={reconnecting} />
    </LanguageProvider>,
  );
}

describe('AgentFlowCanvas', () => {
  beforeEach(() => {
    window.localStorage.clear();
    mockFitView.mockClear();
  });

  it('renders empty state message when trace has no events/agents', () => {
    const trace = makeTrace();
    renderCanvas(trace);

    expect(screen.getByTestId('agent-flow-empty')).toBeInTheDocument();
    expect(screen.getByText('Chưa có luồng agent')).toBeInTheDocument();
    expect(screen.queryByTestId('agent-flow-details')).not.toBeInTheDocument();
  });

  it('renders flow nodes for traced agents', () => {
    const trace = makeTrace({
      events: [
        {
          seq: 1,
          kind: 'step',
          step_id: 's-orch-1',
          node: 'orchestrator',
          action: 'route',
          at: '',
          elapsed_ms: 200,
          duration_ms: 500,
          status: 'finished',
          summary: 'Phân tích yêu cầu',
          outcome_summary: 'Chuyển sang data assistant',
        },
        {
          seq: 2,
          kind: 'transition',
          step_id: 't-1',
          node: 'orchestrator',
          source: 'orchestrator',
          target: 'data_assistant',
          at: '',
          elapsed_ms: 700,
          status: 'finished',
          summary: '',
        },
        {
          seq: 3,
          kind: 'step',
          step_id: 's-da-1',
          node: 'data_assistant',
          action: 'query',
          at: '',
          elapsed_ms: 800,
          duration_ms: 1200,
          status: 'finished',
          summary: 'Truy vấn schema doanh nghiệp',
          outcome_summary: 'Hoàn thành tổng hợp dữ liệu',
        },
      ],
    });

    renderCanvas(trace);

    expect(screen.getByRole('button', { name: /Orchestrator Agent · Hoàn tất/, hidden: true })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Data Assistant Agent · Hoàn tất/, hidden: true })).toBeInTheDocument();
  });

  it('renders compact details section below canvas showing selected agent info', () => {
    const trace = makeTrace({
      events: [
        {
          seq: 1,
          kind: 'step',
          step_id: 's-orch-1',
          node: 'orchestrator',
          action: 'route',
          at: '',
          elapsed_ms: 200,
          duration_ms: 500,
          status: 'finished',
          summary: 'Phân tích yêu cầu',
          outcome_summary: 'Chuyển sang data assistant',
        },
      ],
    });

    renderCanvas(trace);

    const details = screen.getByTestId('agent-flow-details');
    expect(details).toBeInTheDocument();
    expect(details).toHaveTextContent('Orchestrator Agent');
    expect(details).toHaveTextContent('Hoàn tất');
    expect(details).toHaveTextContent('Chuyển sang data assistant');
  });

  it('shows "Chưa có giải thích" when explanation is missing', () => {
    const trace = makeTrace({
      events: [
        {
          seq: 1,
          kind: 'step',
          step_id: 's-orch-1',
          node: 'orchestrator',
          action: 'route',
          at: '',
          elapsed_ms: 200,
          duration_ms: 500,
          status: 'finished',
          summary: '',
          outcome_summary: '',
        },
      ],
    });

    renderCanvas(trace);

    const details = screen.getByTestId('agent-flow-details');
    expect(details).toBeInTheDocument();
    expect(screen.getByTestId('agent-flow-explanation')).toHaveTextContent('Chưa có giải thích');
  });

  it('selecting an agent card updates the detail section to show that agent', () => {
    const trace = makeTrace({
      events: [
        {
          seq: 1,
          kind: 'step',
          step_id: 's-orch-1',
          node: 'orchestrator',
          action: 'route',
          at: '',
          elapsed_ms: 200,
          duration_ms: 500,
          status: 'finished',
          summary: 'Phân tích yêu cầu',
          outcome_summary: 'Chuyển sang data assistant',
        },
        {
          seq: 2,
          kind: 'transition',
          step_id: 't-1',
          node: 'orchestrator',
          source: 'orchestrator',
          target: 'data_assistant',
          at: '',
          elapsed_ms: 700,
          status: 'finished',
          summary: '',
        },
        {
          seq: 3,
          kind: 'step',
          step_id: 's-da-1',
          node: 'data_assistant',
          action: 'query',
          at: '',
          elapsed_ms: 800,
          duration_ms: 1200,
          status: 'finished',
          summary: 'Truy vấn schema doanh nghiệp',
          outcome_summary: 'Hoàn thành tổng hợp dữ liệu',
        },
      ],
    });

    renderCanvas(trace);

    // Initial default selection is first visible agent (Orchestrator)
    expect(screen.getByTestId('agent-flow-details')).toHaveTextContent('Orchestrator Agent');

    // Click data_assistant node
    const daNode = screen.getByRole('button', { name: /Data Assistant Agent · Hoàn tất/, hidden: true });
    fireEvent.click(daNode);

    // Details pane should now show Data Assistant
    const details = screen.getByTestId('agent-flow-details');
    expect(details).toHaveTextContent('Data Assistant Agent');
    expect(details).toHaveTextContent('Hoàn thành tổng hợp dữ liệu');
  });

  it('preserves user selection across incremental streaming updates', () => {
    const initialTrace = makeTrace({
      events: [
        {
          seq: 1,
          kind: 'step',
          step_id: 's-orch-1',
          node: 'orchestrator',
          action: 'route',
          at: '',
          elapsed_ms: 200,
          duration_ms: 500,
          status: 'finished',
          summary: 'Phân tích yêu cầu',
          outcome_summary: 'Chuyển sang data assistant',
        },
        {
          seq: 2,
          kind: 'transition',
          step_id: 't-1',
          node: 'orchestrator',
          source: 'orchestrator',
          target: 'data_assistant',
          at: '',
          elapsed_ms: 700,
          status: 'finished',
          summary: '',
        },
        {
          seq: 3,
          kind: 'step',
          step_id: 's-da-1',
          node: 'data_assistant',
          action: 'query',
          at: '',
          elapsed_ms: 800,
          status: 'started',
          summary: 'Đang truy vấn schema...',
        },
      ],
    });

    const { rerender } = renderCanvas(initialTrace);

    // Select orchestrator node explicitly
    const orchNode = screen.getByRole('button', { name: /Orchestrator Agent · Hoàn tất/, hidden: true });
    fireEvent.click(orchNode);
    expect(screen.getByTestId('agent-flow-details')).toHaveTextContent('Orchestrator Agent');

    // Incremental stream update: data_assistant finishes
    const updatedTrace: ExecutionTrace = {
      ...initialTrace,
      elapsed_ms: 2000,
      events: [
        ...initialTrace.events.slice(0, 2),
        {
          seq: 3,
          kind: 'step',
          step_id: 's-da-1',
          node: 'data_assistant',
          action: 'query',
          at: '',
          elapsed_ms: 800,
          duration_ms: 1200,
          status: 'finished',
          summary: 'Đã truy vấn schema',
          outcome_summary: 'Hoàn thành tổng hợp dữ liệu',
        },
      ],
    };

    rerender(
      <LanguageProvider>
        <AgentFlowCanvas trace={updatedTrace} />
      </LanguageProvider>,
    );

    // User selection should still be Orchestrator!
    expect(screen.getByTestId('agent-flow-details')).toHaveTextContent('Orchestrator Agent');
  });

  it('does not call fitView repeatedly on incremental stream updates (only on mount / run_id change)', () => {
    const traceRun1 = makeTrace({
      run_id: 'run-1',
      events: [
        {
          seq: 1,
          kind: 'step',
          step_id: 's-orch-1',
          node: 'orchestrator',
          action: 'route',
          at: '',
          elapsed_ms: 200,
          status: 'started',
          summary: 'Khởi tạo',
        },
      ],
    });

    const { rerender } = renderCanvas(traceRun1);

    expect(mockFitView).toHaveBeenCalledTimes(1);
    expect(mockFitView).toHaveBeenCalledWith({ padding: 0.15, duration: 300 });

    // Incremental stream update for same run_id
    const traceRun1Updated = makeTrace({
      run_id: 'run-1',
      events: [
        ...traceRun1.events,
        {
          seq: 2,
          kind: 'step',
          step_id: 's-orch-2',
          node: 'orchestrator',
          action: 'route',
          at: '',
          elapsed_ms: 500,
          status: 'finished',
          summary: 'Hoàn thành phân tích',
        },
      ],
    });

    rerender(
      <LanguageProvider>
        <AgentFlowCanvas trace={traceRun1Updated} />
      </LanguageProvider>,
    );

    // fitView should NOT be called again
    expect(mockFitView).toHaveBeenCalledTimes(1);

    // New run with different run_id
    const traceRun2 = makeTrace({
      run_id: 'run-2',
      events: [
        {
          seq: 1,
          kind: 'step',
          step_id: 's-orch-3',
          node: 'orchestrator',
          action: 'route',
          at: '',
          elapsed_ms: 100,
          status: 'started',
          summary: 'Lượt chat mới',
        },
      ],
    });

    rerender(
      <LanguageProvider>
        <AgentFlowCanvas trace={traceRun2} />
      </LanguageProvider>,
    );

    // fitView should be called again for run-2
    expect(mockFitView).toHaveBeenCalledTimes(2);
  });
});
