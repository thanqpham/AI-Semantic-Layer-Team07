import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { ReactFlowProvider } from '@xyflow/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { DiagramControls } from './DiagramControls';

describe('DiagramControls', () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('renders layout mode buttons and notifies on selection', () => {
    const onModeChange = vi.fn();
    render(
      <ReactFlowProvider>
        <DiagramControls
          mode="balanced"
          onModeChange={onModeChange}
          hideIsolated={false}
          onToggleIsolated={vi.fn()}
          isolatedCount={5}
        />
      </ReactFlowProvider>
    );

    const hierarchicalBtn = screen.getByRole('button', { name: /phân tầng/i });
    fireEvent.click(hierarchicalBtn);
    expect(onModeChange).toHaveBeenCalledWith('hierarchical');

    const gridBtn = screen.getByRole('button', { name: /lưới/i });
    fireEvent.click(gridBtn);
    expect(onModeChange).toHaveBeenCalledWith('grid');
  });

  it('shows isolated count badge and toggles state when clicked', () => {
    const onToggleIsolated = vi.fn();
    render(
      <ReactFlowProvider>
        <DiagramControls
          mode="balanced"
          onModeChange={vi.fn()}
          hideIsolated={false}
          onToggleIsolated={onToggleIsolated}
          isolatedCount={12}
        />
      </ReactFlowProvider>
    );

    const toggleBtn = screen.getByRole('button', { name: /ẩn bảng rời/i });
    expect(toggleBtn).toBeInTheDocument();
    fireEvent.click(toggleBtn);
    expect(onToggleIsolated).toHaveBeenCalledTimes(1);
  });
});
