import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AgentThinking, TraceDuration } from './AgentThinking';
import { AgentFlowPanel } from './AgentFlowPanel';
import { StudioChatStream, ChatMessage } from './StudioChatStream';
import { traceFixture } from '@/test/chatTraceFixture';

afterEach(() => { cleanup(); vi.useRealTimers(); });

describe('thinking and agent flow', () => {
  it('scrolls only the chat pane as agent nodes update', () => {
    const props = { messages: [{ id: 'a', sender: 'assistant' as const, text: '', timestamp: '10:00', executionTrace: traceFixture }], onSendMessage: vi.fn(), isLoading: true, tableNames: [] };
    const { container, rerender } = render(<StudioChatStream {...props} />);
    const pane = container.querySelector('.overflow-y-auto') as HTMLElement;
    Object.defineProperty(pane, 'scrollHeight', { configurable: true, value: 600 });
    rerender(<StudioChatStream {...props} messages={[{ ...props.messages[0], executionTrace: { ...traceFixture, elapsed_ms: 3000 } }]} />);
    expect(pane.scrollTop).toBe(600);
  });

  it('starts closed, ticks when closed, and preserves expansion on completion', () => {
    vi.useFakeTimers();
    const props = { trace: traceFixture, onOpenGraph: vi.fn() };
    const { rerender } = render(<AgentThinking {...props} />);
    expect(screen.queryByText('Phân loại yêu cầu')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Thinking/ })).toHaveAttribute('aria-expanded', 'false');
    act(() => { vi.advanceTimersByTime(3000); });
    expect(screen.getByText('5 s')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Thinking/ }));
    expect(screen.getByText('Phân loại yêu cầu')).toBeInTheDocument();
    const completed = { ...traceFixture, status: 'completed' as const, elapsed_ms: 6000, events: [
      ...traceFixture.events, { ...traceFixture.events[1], seq: 3, status: 'finished' as const, duration_ms: 6000 },
    ] };
    rerender(<AgentThinking {...props} trace={completed} />);
    expect(screen.getByRole('button', { name: /Thinking.*Hoàn tất/ })).toHaveAttribute('aria-expanded', 'true');
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
    const { rerender, container } = render(<StudioChatStream {...props} />);
    const trigger = screen.getByRole('button', { name: 'Luồng agent' });
    fireEvent.click(trigger);
    expect(screen.getByRole('heading', { name: 'Luồng agent' })).toBeInTheDocument();
    expect(screen.getByText('Doanh thu tháng này', { selector: 'p' })).toBeInTheDocument();
    expect(container.querySelector('[data-edge="request-orchestrator"]')).toHaveAttribute('data-taken', 'true');
    expect(container.querySelector('[data-edge="orchestrator-semantic_parse"]')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Thinking/ })).toHaveAttribute('aria-expanded', 'false');
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('heading', { name: 'Luồng agent' })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    fireEvent.click(trigger);
    rerender(<StudioChatStream {...props} conversationKey="session-2" messages={[]} />);
    expect(screen.queryByRole('heading', { name: 'Luồng agent' })).not.toBeInTheDocument();
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
    const { container, rerender } = render(<AgentFlowPanel trace={trace} title="Doanh thu tháng này" onClose={vi.fn()} trigger={null} />);

    expect(screen.getByRole('button', { name: /Orchestrator.*Đang chạy/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Data Assistant.*Đang chạy/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Conversation Agent/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Metric Designer Agent/ })).not.toBeInTheDocument();
    const edge = container.querySelector('[data-edge="orchestrator-data_assistant"]');
    expect(edge).toBeInTheDocument();
    expect(edge).toHaveAttribute('data-edge-status', 'running');
    expect(edge).not.toHaveAttribute('stroke-dasharray');
    expect(screen.getByRole('button', { name: /Orchestrator/ })).toHaveClass('rounded-full');

    const nodePositions = [...container.querySelectorAll<HTMLButtonElement>('[aria-pressed]')]
      .map((node) => {
        const position = node.parentElement?.classList.contains('absolute') ? node.parentElement : node;
        return `${position?.style.left},${position?.style.top}`;
      });
    expect(new Set(nodePositions).size).toBe(nodePositions.length);
    expect(container.querySelector('aside')).toHaveClass('overflow-hidden');

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
    rerender(<AgentFlowPanel trace={completedTrace} title="Doanh thu tháng này" onClose={vi.fn()} trigger={null} />);
    expect(screen.getByRole('button', { name: /Phản hồi.*Hoàn tất/ })).toBeInTheDocument();
    expect(container.querySelector('[data-edge="data_assistant-response"]')).toBeInTheDocument();
    const completedEdge = container.querySelector('[data-edge="orchestrator-data_assistant"]');
    expect(completedEdge).toHaveAttribute('data-edge-status', 'completed');
    expect(completedEdge).toHaveAttribute('stroke-dasharray', '5 5');
    const xPosition = (name: RegExp) => Number.parseFloat(
      screen.getByRole('button', { name }).parentElement?.style.left || screen.getByRole('button', { name }).style.left,
    );
    expect(xPosition(/Yêu cầu|Request/)).toBeLessThan(xPosition(/Orchestrator/));
    expect(xPosition(/Orchestrator/)).toBeLessThan(xPosition(/Data Assistant/));
    expect(xPosition(/Data Assistant/)).toBeLessThan(xPosition(/Phản hồi/));
  });

  it('resizes the desktop agent flow with pointer drag and keyboard controls', () => {
    const originalMatchMedia = window.matchMedia;
    window.matchMedia = vi.fn().mockReturnValue({ matches: false });
    try {
      const { container } = render(<AgentFlowPanel trace={traceFixture} title="Request" onClose={vi.fn()} trigger={null} />);
      const panel = screen.getByRole('complementary');
      const separator = screen.getByRole('separator', { name: 'Thay đổi kích thước luồng agent' });
      Object.assign(separator, {
        setPointerCapture: vi.fn(),
        hasPointerCapture: vi.fn().mockReturnValue(true),
        releasePointerCapture: vi.fn(),
      });

      expect(panel).toHaveStyle({ width: '440px' });
      fireEvent.pointerDown(separator, { pointerId: 1, clientX: 800 });
      fireEvent.pointerMove(separator, { pointerId: 1, clientX: 740 });
      fireEvent.pointerUp(separator, { pointerId: 1 });
      expect(panel).toHaveStyle({ width: '500px' });
      fireEvent.keyDown(separator, { key: 'ArrowRight' });
      expect(panel).toHaveStyle({ width: '484px' });
      expect(container.querySelector('[aria-valuenow="484"]')).toBe(separator);
    } finally {
      cleanup();
      window.matchMedia = originalMatchMedia;
    }
  });

  it('reflows the graph as its available panel size changes', () => {
    const originalMatchMedia = window.matchMedia;
    const originalResizeObserver = globalThis.ResizeObserver;
    let resize!: ResizeObserverCallback;
    vi.stubGlobal('ResizeObserver', class {
      constructor(callback: ResizeObserverCallback) { resize = callback; }
      observe() {}
      disconnect() {}
      unobserve() {}
    });
    window.matchMedia = vi.fn().mockReturnValue({ matches: false });
    const trace = {
      ...traceFixture,
      status: 'completed' as const,
      events: [
        ...traceFixture.events,
        { seq: 3, kind: 'transition' as const, step_id: 'edge-data', node: 'data_assistant', source: 'orchestrator', target: 'data_assistant',
          at: '', elapsed_ms: 1000, status: 'finished' as const, summary: '' },
        { seq: 4, kind: 'transition' as const, step_id: 'edge-response', node: 'response', source: 'data_assistant', target: 'response',
          at: '', elapsed_ms: 2000, status: 'finished' as const, summary: '' },
      ],
    };
    try {
      const { container } = render(<AgentFlowPanel trace={trace} title="Request" onClose={vi.fn()} trigger={null} />);
      const graph = container.querySelector('[aria-label="Sơ đồ thực thi agent"]')!;

      act(() => resize([{ target: graph, contentRect: { width: 280, height: 500 } } as ResizeObserverEntry], {} as ResizeObserver));
      expect(graph.querySelector('svg')).toHaveAttribute('viewBox', '0 0 528 500');

      act(() => resize([{ target: graph, contentRect: { width: 660, height: 500 } } as ResizeObserverEntry], {} as ResizeObserver));
      expect(graph.querySelector('svg')).toHaveAttribute('viewBox', '0 0 660 500');
    } finally {
      cleanup();
      window.matchMedia = originalMatchMedia;
      vi.stubGlobal('ResizeObserver', originalResizeObserver);
    }
  });

  it.each(['needs_clarification', 'error'] as const)('shows the terminal status %s and freezes time', (status) => {
    render(<AgentThinking trace={{ ...traceFixture, status }} onOpenGraph={vi.fn()} />);
    expect(screen.getByRole('button', { name: status === 'error' ? /Có lỗi/ : /Cần làm rõ/ })).toBeInTheDocument();
  });

  it('traps mobile focus, makes the chat inert, and restores focus on close', () => {
    window.matchMedia = vi.fn().mockReturnValue({ matches: true });
    const { container } = render(<StudioChatStream messages={[
      { id: 'assistant', sender: 'assistant', text: '', timestamp: '10:00', executionTrace: traceFixture },
    ]} onSendMessage={vi.fn()} isLoading tableNames={[]} />);
    const trigger = screen.getByRole('button', { name: 'Luồng agent' });
    fireEvent.click(trigger);
    const panel = screen.getByRole('dialog', { name: 'Luồng agent' });
    expect(panel).toHaveAttribute('aria-modal', 'true');
    expect(container.querySelector('[inert]')).toBeInTheDocument();
    const close = screen.getByRole('button', { name: 'Đóng luồng agent' });
    expect(close).toHaveFocus();
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
    expect(screen.getByRole('button', { name: /Orchestrator/ })).toHaveFocus();
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(close).toHaveFocus();
    fireEvent.click(close);
    expect(container.querySelector('[inert]')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
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
