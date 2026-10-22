import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AgentThinking, TraceDuration } from './AgentThinking';
import { StudioChatStream, ChatMessage } from './StudioChatStream';
import { traceFixture } from '@/test/chatTraceFixture';

afterEach(() => { cleanup(); vi.useRealTimers(); });

describe('thinking and agent flow', () => {
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
    expect(container.querySelector('[data-edge="orchestrator-semantic_parse"]')).toHaveAttribute('data-taken', 'false');
    expect(screen.getByRole('button', { name: /Thinking/ })).toHaveAttribute('aria-expanded', 'false');
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('heading', { name: 'Luồng agent' })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    fireEvent.click(trigger);
    rerender(<StudioChatStream {...props} conversationKey="session-2" messages={[]} />);
    expect(screen.queryByRole('heading', { name: 'Luồng agent' })).not.toBeInTheDocument();
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
    expect(screen.getByRole('button', { name: /Phản hồi/ })).toHaveFocus();
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
