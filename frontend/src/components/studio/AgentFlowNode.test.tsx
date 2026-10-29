import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { ReactFlowProvider, type NodeProps } from '@xyflow/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AgentFlowNode } from './AgentFlowNode';
import { LanguageProvider } from '@/context/LanguageContext';
import type { AgentFlowNode as AgentFlowNodeType, AgentNodeData } from '@/lib/agentFlowGraph';

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function createMockNodeProps(
  dataOverrides: Partial<AgentNodeData> = {},
  selected = false,
): NodeProps<AgentFlowNodeType> {
  const data: AgentNodeData = {
    id: 'orchestrator',
    name: 'Orchestrator Agent',
    enName: 'Orchestrator Agent (EN)',
    status: 'completed',
    selected: false,
    ...dataOverrides,
  };

  return {
    id: data.id,
    type: 'agentNode',
    data,
    selected,
    zIndex: 0,
    isConnectable: false,
    positionAbsoluteX: 0,
    positionAbsoluteY: 0,
    dragging: false,
    selectable: true,
    deletable: false,
    draggable: false,
    parentId: undefined,
  } as unknown as NodeProps<AgentFlowNodeType>;
}

function renderNode(props: NodeProps<AgentFlowNodeType>) {
  return render(
    <LanguageProvider>
      <ReactFlowProvider>
        <AgentFlowNode {...props} />
      </ReactFlowProvider>
    </LanguageProvider>,
  );
}

describe('AgentFlowNode', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('renders agent name, icon, and status icon for completed status', () => {
    const props = createMockNodeProps({ status: 'completed' });
    renderNode(props);

    const button = screen.getByRole('button', { name: /Orchestrator Agent · Hoàn tất/ });
    expect(button).toBeInTheDocument();
    expect(button).toHaveTextContent('Orchestrator Agent');
    expect(button).toHaveTextContent('Hoàn tất');

    // Bot icon present
    const botIcon = button.querySelector('svg.bot-message-icon');
    expect(botIcon).toBeInTheDocument();

    // Completed icon has emerald color
    const completedIcon = button.querySelector('svg.text-emerald-500');
    expect(completedIcon).toBeInTheDocument();
  });

  it('renders spinner with reduced-motion support for running status', () => {
    const props = createMockNodeProps({ status: 'running' });
    renderNode(props);

    const button = screen.getByRole('button', { name: /Orchestrator Agent · Đang chạy/ });
    expect(button).toBeInTheDocument();

    const spinner = button.querySelector('svg.animate-spin');
    expect(spinner).toBeInTheDocument();
    expect(spinner).toHaveClass('text-blue-500');
    expect(spinner).toHaveClass('motion-reduce:animate-none');
  });

  it('renders alert icon for error status', () => {
    const props = createMockNodeProps({ status: 'error' });
    renderNode(props);

    const button = screen.getByRole('button', { name: /Orchestrator Agent · Có lỗi/ });
    expect(button).toBeInTheDocument();

    const alertIcon = button.querySelector('svg.text-red-500');
    expect(alertIcon).toBeInTheDocument();
  });

  it('renders idle dot indicator for idle status', () => {
    const props = createMockNodeProps({ status: 'idle' });
    renderNode(props);

    const button = screen.getByRole('button', { name: /Orchestrator Agent · Chờ xử lý/ });
    expect(button).toBeInTheDocument();

    const idleDot = button.querySelector('span.rounded-full.bg-muted-foreground\\/40');
    expect(idleDot).toBeInTheDocument();
  });

  it('formats name and status in English when language is en', () => {
    window.localStorage.setItem('app_language', 'en');
    const props = createMockNodeProps({ status: 'completed' });
    renderNode(props);

    const button = screen.getByRole('button', { name: /Orchestrator Agent \(EN\) · Completed/ });
    expect(button).toBeInTheDocument();
    expect(button).toHaveTextContent('Orchestrator Agent (EN)');
    expect(button).toHaveTextContent('Completed');
  });

  it('shows selected ring and outline when data.selected is true', () => {
    const props = createMockNodeProps({ selected: true });
    renderNode(props);

    const button = screen.getByRole('button');
    expect(button).toHaveAttribute('aria-pressed', 'true');
    expect(button).toHaveClass('ring-2');
    expect(button).toHaveClass('ring-primary');
    expect(button).toHaveClass('border-primary');
  });

  it('shows selected ring when props.selected is true', () => {
    const props = createMockNodeProps({ selected: false }, true);
    renderNode(props);

    const button = screen.getByRole('button');
    expect(button).toHaveAttribute('aria-pressed', 'true');
    expect(button).toHaveClass('ring-2');
    expect(button).toHaveClass('ring-primary');
  });

  it('is not pressed and has default border when unselected', () => {
    const props = createMockNodeProps({ selected: false }, false);
    renderNode(props);

    const button = screen.getByRole('button');
    expect(button).toHaveAttribute('aria-pressed', 'false');
    expect(button).not.toHaveClass('ring-2');
  });

  it('triggers selection on Enter and Space keypress', () => {
    const onSelect = vi.fn();
    const props = createMockNodeProps({ id: 'metric_suggest', onSelect });
    renderNode(props);

    const button = screen.getByRole('button');
    fireEvent.keyDown(button, { key: 'Enter' });
    expect(onSelect).toHaveBeenCalledWith('metric_suggest');

    fireEvent.keyDown(button, { key: ' ' });
    expect(onSelect).toHaveBeenCalledTimes(2);

    fireEvent.keyDown(button, { key: 'ArrowDown' });
    expect(onSelect).toHaveBeenCalledTimes(2);
  });

  it('triggers selection when clicked directly', () => {
    const onSelect = vi.fn();
    const props = createMockNodeProps({ id: 'metric_review', onSelect });
    renderNode(props);

    const button = screen.getByRole('button');
    fireEvent.click(button);
    expect(onSelect).toHaveBeenCalledWith('metric_review');
  });
});
