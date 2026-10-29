import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AgentThinking, TraceDuration } from './AgentThinking';
import { StudioChatStream, ChatMessage } from './StudioChatStream';
import { traceFixture } from '@/test/chatTraceFixture';
import { buildAgentFlowGraph } from '@/lib/agentFlowGraph';

afterEach(() => { cleanup(); vi.useRealTimers(); });

describe('thinking and agent flow', () => {
  it('shows agents once and hides system steps in the timeline and flow', () => {
    window.matchMedia = vi.fn().mockReturnValue({ matches: false });
    const event = (seq: number, node: string, action: string, status: 'started' | 'finished') => ({
      seq, kind: 'step' as const, step_id: `step-${seq}`, node, action, at: '', elapsed_ms: seq, status, summary: action,
    });
    const trace = { ...traceFixture, events: [
      ...traceFixture.events, event(3, 'context', 'context', 'finished'),
      event(4, 'metric_review', 'metric_review', 'started'),
      event(5, 'metric_review', 'metric_review_decision', 'started'),
      event(6, 'metric_review', 'metric_review_decision', 'finished'),
    ] };
    render(<AgentThinking trace={trace} />);
    fireEvent.click(screen.getByRole('button', { name: 'Luồng agent' }));
    const timeline = screen.getByRole('list', { name: 'Hoạt động trực tiếp' });
    expect(timeline.querySelectorAll('li')).toHaveLength(2);
    expect(timeline).toHaveTextContent('Metric Reviewer Agent');
    expect(timeline).not.toHaveTextContent('Chuẩn bị schema');
    expect(screen.queryByRole('button', { name: /Chuẩn bị ngữ cảnh/ })).not.toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: /Metric Reviewer Agent/, hidden: true })).toHaveLength(1);
  });

  it('connects agents only through observed transitions across hidden steps', () => {
    window.matchMedia = vi.fn().mockReturnValue({ matches: false });
    const edge = (seq: number, source: string, target: string) => ({
      seq, kind: 'transition' as const, step_id: `edge-${seq}`, node: target, source, target,
      at: '', elapsed_ms: seq, status: 'finished' as const, summary: '',
    });
    const trace = { ...traceFixture, events: [
      ...traceFixture.events, edge(3, 'orchestrator', 'context'), edge(4, 'context', 'metric_coordinator'),
      edge(5, 'metric_coordinator', 'metric_suggest'), edge(6, 'metric_suggest', 'metric_validate'),
      edge(7, 'metric_validate', 'metric_review'),
    ] };
    const { edges } = buildAgentFlowGraph(trace);
    expect(edges.some((e) => e.source === 'orchestrator' && e.target === 'metric_suggest')).toBe(true);
    expect(edges.some((e) => e.source === 'metric_suggest' && e.target === 'metric_review')).toBe(true);
    expect(edges.some((e) => e.source === 'orchestrator' && e.target === 'metric_review')).toBe(false);
  });
  it('scrolls only the chat pane as agent nodes update', () => {
    const props = { messages: [{ id: 'a', sender: 'assistant' as const, text: '', timestamp: '10:00', executionTrace: traceFixture }], onSendMessage: vi.fn(), isLoading: true, tableNames: [] };
    const { container, rerender } = render(<StudioChatStream {...props} />);
    const pane = container.querySelector('.overflow-y-auto') as HTMLElement;
    Object.defineProperty(pane, 'scrollHeight', { configurable: true, value: 600 });
    rerender(<StudioChatStream {...props} messages={[{ ...props.messages[0], executionTrace: { ...traceFixture, elapsed_ms: 3000 } }]} />);
    expect(pane.scrollTop).toBe(600);
  });

  it('starts closed, ticks when closed, and preserves its expanded state after completion', () => {
    vi.useFakeTimers();
    const props = { trace: traceFixture, onOpenGraph: vi.fn() };
    const { rerender } = render(<AgentThinking {...props} />);
    expect(screen.queryByText('Phân loại yêu cầu')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Thinking/ })).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByRole('button', { name: /Thinking/ })).toHaveClass('min-h-8');
    act(() => { vi.advanceTimersByTime(3000); });
    expect(screen.getByText('5 s')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Thinking/ }));
    expect(screen.getAllByText('Orchestrator Agent').length).toBeGreaterThan(0);
    const completed = { ...traceFixture, status: 'completed' as const, elapsed_ms: 6000, events: [
      ...traceFixture.events, { ...traceFixture.events[1], seq: 3, status: 'finished' as const, duration_ms: 6000 },
    ] };
    rerender(<AgentThinking {...props} trace={completed} />);
    expect(screen.getByRole('button', { name: /Thinking.*Hoàn tất/ })).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getAllByText('Orchestrator Agent').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Orchestrator Agent').length).toBeGreaterThan(0);
    act(() => { vi.advanceTimersByTime(5000); });
    expect(screen.queryByText('11 s')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Luồng agent' }));
    expect(props.onOpenGraph).toHaveBeenCalledOnce();
  });

  it('opens the graph independently, highlights only observed edges, and closes on session change', () => {
    window.matchMedia = vi.fn().mockReturnValue({ matches: true });
    const messages: ChatMessage[] = [
      { id: 'user', sender: 'user', text: 'Doanh thu tháng này', timestamp: '10:00' },
      { id: 'assistant', sender: 'assistant', text: '', timestamp: '10:00', executionTrace: traceFixture },
    ];
    const props = { messages, conversationKey: 'session-1', onSendMessage: vi.fn(), isLoading: true, tableNames: [] };
    const { rerender } = render(<StudioChatStream {...props} />);
    const trigger = screen.getByRole('button', { name: 'Luồng agent' });
    fireEvent.click(trigger);
    expect(screen.getByRole('heading', { name: 'Luồng agent' })).toBeInTheDocument();
    expect(screen.getByTestId('agent-flow-canvas-container')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Orchestrator Agent/, hidden: true })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Thinking/ })).toHaveAttribute('aria-expanded', 'true');
    rerender(<StudioChatStream {...props} conversationKey="session-2" messages={[]} />);
    expect(screen.queryByRole('heading', { name: 'Luồng agent' })).not.toBeInTheDocument();
  });

  it('updates one row when a step finishes and ignores transitions', () => {
    const started = { seq: 3, kind: 'step' as const, step_id: 'live', node: 'data_assistant',
      at: '', elapsed_ms: 10, status: 'started' as const, summary: 'Working' };
    const props = { trace: { ...traceFixture, events: [...traceFixture.events, started] }, onOpenGraph: vi.fn() };
    const { rerender } = render(<AgentThinking {...props} />);
    fireEvent.click(screen.getByRole('button', { name: /Thinking/ }));
    const timeline = screen.getByRole('list', { name: 'Ho\u1ea1t \u0111\u1ed9ng tr\u1ef1c ti\u1ebfp' });
    expect(timeline.querySelectorAll('li')).toHaveLength(2);
    expect(timeline.querySelectorAll('li')[1]).toHaveTextContent('\u0110ang ch\u1ea1y');
    const finished = { ...started, seq: 4, status: 'finished' as const, duration_ms: 300, outcome_summary: 'Result' };
    rerender(<AgentThinking {...props} trace={{ ...props.trace, events: [...props.trace.events, finished] }} />);
    expect(timeline.querySelectorAll('li')).toHaveLength(2);
    expect(timeline.querySelectorAll('li')[1]).toHaveTextContent('Ho\u00e0n t\u1ea5t');
    expect(timeline.querySelectorAll('li')[1]).toHaveTextContent('Result');
    const again = { ...started, seq: 5, step_id: 'another' };
    rerender(<AgentThinking {...props} trace={{ ...props.trace, events: [...props.trace.events, finished, again] }} />);
    expect(timeline.querySelectorAll('li')).toHaveLength(2);
  });

  it('shows an outcome beside the action on one invocation as it updates', () => {
    const started = { seq: 3, kind: 'step' as const, step_id: 'outcome-step', node: 'metric_suggest', action: 'metric_suggest',
      at: '', elapsed_ms: 10, status: 'started' as const, summary: 'Đề xuất định nghĩa metric' };
    const { rerender } = render(<AgentThinking trace={{ ...traceFixture, status: 'running', events: [...traceFixture.events, started] }} onOpenGraph={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /Thinking/ }));
    const completed = { ...started, seq: 4, status: 'finished' as const, duration_ms: 20, outcome_summary: 'Đề xuất 2 metric' };
    rerender(<AgentThinking trace={{ ...traceFixture, status: 'completed', events: [...traceFixture.events, started, completed] }} onOpenGraph={vi.fn()} />);
    const timeline = screen.getByRole('list', { name: 'Hoạt động trực tiếp' });
    expect(timeline).not.toHaveTextContent('Đề xuất định nghĩa metric');
    expect(timeline).toHaveTextContent('Đề xuất 2 metric');
    expect(timeline.querySelectorAll('li')).toHaveLength(2);
  });

  it('expands each agent explanation and updates it when the step finishes', () => {
    const started = { seq: 3, kind: 'step' as const, step_id: 'explain', node: 'semantic_parse',
      at: '', elapsed_ms: 10, status: 'started' as const, summary: 'Analyzing' };
    const trace = { ...traceFixture, events: [...traceFixture.events, started] };
    const { rerender } = render(<AgentThinking trace={trace} onOpenGraph={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /Thinking/ }));
    const controls = screen.getAllByLabelText(/^Xem giải thích:/);
    const detail = controls[1].closest('details')!;
    expect(controls[1]).toHaveTextContent('Semantic Query Parser Agent');
    expect(controls[1]).not.toHaveTextContent('Xem giải thích');
    expect(screen.queryByText('Analyzing')).not.toBeInTheDocument();
    expect(detail).not.toHaveAttribute('open');
    fireEvent.click(controls[1]);
    expect(detail).toHaveAttribute('open');
    expect(detail).toHaveTextContent('Chưa có giải thích');
    const finished = { ...started, seq: 4, status: 'finished' as const, outcome_summary: 'Revenue by customer' };
    rerender(<AgentThinking trace={{ ...trace, events: [...trace.events, finished] }} onOpenGraph={vi.fn()} />);
    expect(detail).toHaveAttribute('open');
    expect(detail).toHaveTextContent('Revenue by customer');
    fireEvent.click(controls[1]);
    expect(detail).not.toHaveAttribute('open');
  });

  it('renders each trace seq once after repeated snapshots', () => {
    const trace = { ...traceFixture, status: 'running' as const, events: [
      ...traceFixture.events,
      { seq: 3, kind: 'step' as const, step_id: 'step-live', node: 'orchestrator', action: 'internal_action_id',
        at: '', elapsed_ms: 1500, status: 'started' as const, summary: 'Live event' },
    ] };
    const { rerender } = render(<AgentThinking trace={trace} onOpenGraph={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /Thinking/ }));
    rerender(<AgentThinking trace={{ ...trace, events: [...trace.events, trace.events[2]] }} onOpenGraph={vi.fn()} />);
    expect(screen.getByRole('list', { name: 'Hoạt động trực tiếp' }).querySelectorAll('li')).toHaveLength(1);
  });

  it('follows new events only while the timeline is at the bottom', () => {
    const trace = { ...traceFixture, events: [...traceFixture.events] };
    const { rerender } = render(<AgentThinking trace={trace} onOpenGraph={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /Thinking/ }));
    const timeline = screen.getByRole('list', { name: 'Hoạt động trực tiếp' });
    Object.defineProperties(timeline, {
      scrollHeight: { configurable: true, value: 100 },
      clientHeight: { configurable: true, value: 50 },
      scrollTop: { configurable: true, writable: true, value: 50 },
    });
    const appended = { seq: 3, kind: 'step' as const, step_id: 's3', node: 'orchestrator', at: '', elapsed_ms: 3,
      status: 'finished' as const, summary: 'At bottom' };
    rerender(<AgentThinking trace={{ ...trace, events: [...trace.events, appended] }} onOpenGraph={vi.fn()} />);
    expect(timeline.scrollTop).toBe(100);
    Object.defineProperty(timeline, 'scrollTop', { configurable: true, writable: true, value: 20 });
    fireEvent.scroll(timeline);
    const next = { ...appended, seq: 4, step_id: 's4', summary: 'Reviewing history' };
    rerender(<AgentThinking trace={{ ...trace, events: [...trace.events, appended, next] }} onOpenGraph={vi.fn()} />);
    expect(timeline.scrollTop).toBe(20);
  });

  it('shows the accumulating answer only in Thinking while streaming', () => {
    const message: ChatMessage = { id: 'assistant', sender: 'assistant', text: 'Đang tổng hợp kết quả', timestamp: '10:00', executionTrace: traceFixture };
    render(<StudioChatStream messages={[message]} onSendMessage={vi.fn()} isLoading tableNames={[]} />);
    fireEvent.click(screen.getByRole('button', { name: /Thinking/ }));
    expect(screen.getAllByText('Đang tổng hợp kết quả')).toHaveLength(1);
    expect(screen.getByText('Đang tổng hợp kết quả').closest('[data-thinking-answer]')).toBeInTheDocument();
  });

  it('restores the answer to its normal position after completion', () => {
    const message: ChatMessage = { id: 'assistant', sender: 'assistant', text: 'Kết quả hoàn tất', timestamp: '10:00', executionTrace: traceFixture };
    const { rerender } = render(<StudioChatStream messages={[message]} onSendMessage={vi.fn()} isLoading tableNames={[]} />);
    rerender(<StudioChatStream messages={[{ ...message, executionTrace: { ...traceFixture, status: 'completed' } }]} onSendMessage={vi.fn()} isLoading={false} tableNames={[]} />);
    expect(screen.getByText('Kết quả hoàn tất')).toBeInTheDocument();
    expect(screen.queryByText('Final answer')).not.toBeInTheDocument();
  });

  it('keeps normal answer placement while reconnecting', () => {
    const message: ChatMessage = { id: 'assistant', sender: 'assistant', text: 'Đang khôi phục', timestamp: '10:00', executionTrace: traceFixture, reconnecting: true };
    render(<StudioChatStream messages={[message]} onSendMessage={vi.fn()} isLoading tableNames={[]} />);
    expect(screen.getByText('Đang khôi phục')).toBeInTheDocument();
  });

  it('shows only traced agents and lays them out without overlapping nodes', () => {
    const trace = {
      ...traceFixture,
      events: [
        ...traceFixture.events,
        { seq: 3, kind: 'transition' as const, step_id: 'edge-2', node: 'data_assistant', source: 'orchestrator', target: 'data_assistant',
          at: '', elapsed_ms: 1000, status: 'finished' as const, summary: '' },
        { seq: 4, kind: 'step' as const, step_id: 'step-2', node: 'data_assistant', action: 'data_assistant',
          at: '', elapsed_ms: 1000, status: 'started' as const, summary: 'Tra cứu dữ liệu' },
      ],
    };
    const { nodes, edges } = buildAgentFlowGraph(trace);
    expect(nodes.map((n) => n.id)).toEqual(['orchestrator', 'data_assistant']);
    const edge = edges.find((e) => e.source === 'orchestrator' && e.target === 'data_assistant');
    expect(edge).toBeDefined();
    expect(edge?.animated).toBe(true);
    expect(nodes.find((n) => n.id === 'data_assistant')?.data.status).toBe('running');

    const positions = nodes.map((n) => `${n.position.x},${n.position.y}`);
    expect(new Set(positions).size).toBe(positions.length);

    const completedTrace = {
      ...trace,
      status: 'completed' as const,
      events: [
        ...trace.events,
        { seq: 5, kind: 'step' as const, step_id: 'step-2', node: 'data_assistant', action: 'data_assistant',
          at: '', elapsed_ms: 2000, status: 'finished' as const, summary: 'Tra cứu dữ liệu' },
        { seq: 6, kind: 'transition' as const, step_id: 'edge-response', node: 'response',
          source: 'data_assistant', target: 'response', at: '', elapsed_ms: 2000,
          status: 'finished' as const, summary: '' },
      ],
    };
    const completedGraph = buildAgentFlowGraph(completedTrace);
    expect(completedGraph.nodes.some((n) => n.id === 'response')).toBe(false);
    expect(completedGraph.edges.some((e) => e.target === 'response')).toBe(false);
    const completedEdge = completedGraph.edges.find((e) => e.source === 'orchestrator' && e.target === 'data_assistant');
    expect(completedEdge?.animated).toBe(false);
    expect(completedGraph.nodes.find((n) => n.id === 'data_assistant')?.data.status).toBe('completed');
  });

  it.each(['needs_clarification', 'error'] as const)('shows the terminal status %s and freezes time', (status) => {
    render(<AgentThinking trace={{ ...traceFixture, status }} onOpenGraph={vi.fn()} />);
    expect(screen.getByRole('button', { name: status === 'error' ? /Có lỗi/ : /Cần làm rõ/ })).toBeInTheDocument();
  });
});

describe('embedded agent flow in Thinking with dual toggle', () => {
  it('opens Thinking and renders canvas above timeline when clicking Luồng agent from closed state', () => {
    const onOpenGraph = vi.fn();
    render(<AgentThinking trace={traceFixture} onOpenGraph={onOpenGraph} />);
    const headerToggle = screen.getByRole('button', { name: /Thinking/ });
    const flowButton = screen.getByRole('button', { name: 'Luồng agent' });

    expect(headerToggle).toHaveAttribute('aria-expanded', 'false');
    expect(flowButton).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByTestId('agent-flow-canvas-container')).not.toBeInTheDocument();

    fireEvent.click(flowButton);

    expect(onOpenGraph).toHaveBeenCalledOnce();
    expect(headerToggle).toHaveAttribute('aria-expanded', 'true');
    expect(flowButton).toHaveAttribute('aria-expanded', 'true');

    const flowControlsId = flowButton.getAttribute('aria-controls');
    expect(flowControlsId).toBeTruthy();

    const canvas = screen.getByTestId('agent-flow-canvas-container');
    const timeline = screen.getByRole('list', { name: 'Hoạt động trực tiếp' });
    expect(canvas).toBeInTheDocument();
    expect(timeline).toBeInTheDocument();

    const flowContainer = document.getElementById(flowControlsId!);
    expect(flowContainer).toBeInTheDocument();
    expect(flowContainer).toContainElement(canvas);

    // Canvas must be located above the timeline in DOM order
    expect(flowContainer!.compareDocumentPosition(timeline) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('collapses ONLY the canvas when clicking Luồng agent while Thinking is open with canvas', () => {
    render(<AgentThinking trace={traceFixture} />);
    const headerToggle = screen.getByRole('button', { name: /Thinking/ });
    const flowButton = screen.getByRole('button', { name: 'Luồng agent' });

    // Open both via Luồng agent button
    fireEvent.click(flowButton);
    expect(headerToggle).toHaveAttribute('aria-expanded', 'true');
    expect(flowButton).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByTestId('agent-flow-canvas-container')).toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'Hoạt động trực tiếp' })).toBeInTheDocument();

    // Click Luồng agent again: should collapse only the canvas
    fireEvent.click(flowButton);
    expect(headerToggle).toHaveAttribute('aria-expanded', 'true');
    expect(flowButton).toHaveAttribute('aria-expanded', 'false');
    expect(flowButton).not.toHaveAttribute('aria-controls');
    expect(screen.queryByTestId('agent-flow-canvas-container')).not.toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'Hoạt động trực tiếp' })).toBeInTheDocument();
  });

  it('opens canvas above timeline when clicking Luồng agent while Thinking is open without canvas', () => {
    render(<AgentThinking trace={traceFixture} />);
    const headerToggle = screen.getByRole('button', { name: /Thinking/ });
    const flowButton = screen.getByRole('button', { name: 'Luồng agent' });

    // Open Thinking only via header button
    fireEvent.click(headerToggle);
    expect(headerToggle).toHaveAttribute('aria-expanded', 'true');
    expect(flowButton).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByTestId('agent-flow-canvas-container')).not.toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'Hoạt động trực tiếp' })).toBeInTheDocument();

    // Click Luồng agent: opens canvas
    fireEvent.click(flowButton);
    expect(headerToggle).toHaveAttribute('aria-expanded', 'true');
    expect(flowButton).toHaveAttribute('aria-expanded', 'true');
    const canvas = screen.getByTestId('agent-flow-canvas-container');
    const timeline = screen.getByRole('list', { name: 'Hoạt động trực tiếp' });
    expect(canvas).toBeInTheDocument();
    expect(canvas.compareDocumentPosition(timeline) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('toggles Thinking open and closed via the main header button', () => {
    render(<AgentThinking trace={traceFixture} />);
    const headerToggle = screen.getByRole('button', { name: /Thinking/ });
    const flowButton = screen.getByRole('button', { name: 'Luồng agent' });

    // Open both via flow button
    fireEvent.click(flowButton);
    expect(headerToggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByTestId('agent-flow-canvas-container')).toBeInTheDocument();

    // Close Thinking via header button
    fireEvent.click(headerToggle);
    expect(headerToggle).toHaveAttribute('aria-expanded', 'false');
    expect(flowButton).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByTestId('agent-flow-canvas-container')).not.toBeInTheDocument();
    expect(screen.queryByRole('list', { name: 'Hoạt động trực tiếp' })).not.toBeInTheDocument();

    // Re-open via header button: Thinking is open, canvas is closed (or preserves state)
    fireEvent.click(headerToggle);
    expect(headerToggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('list', { name: 'Hoạt động trực tiếp' })).toBeInTheDocument();
  });
});

describe('trace duration units', () => {
  it.each([
    [0, '0 s'], [1, '0.001 s'], [125, '0.125 s'], [999, '0.999 s'],
    [1000, '1 s'], [59999, '59 s'], [60000, '1 m 0 s'], [90500, '1 m 30 s'],
  ])('formats %i ms as %s', (milliseconds, expected) => {
    render(<TraceDuration milliseconds={milliseconds} />);
    expect(screen.getByText(expected)).toBeInTheDocument();
  });
});
