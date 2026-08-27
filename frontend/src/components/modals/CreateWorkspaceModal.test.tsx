import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { CreateWorkspaceModal } from '@/components/modals/CreateWorkspaceModal';

const createWorkspace = vi.hoisted(() => vi.fn());

vi.mock('@/context/WorkspaceContext', () => ({
  useWorkspace: () => ({ createWorkspace }),
}));

describe('CreateWorkspaceModal', () => {
  afterEach(() => {
    cleanup();
    createWorkspace.mockReset();
  });

  it('rejects an empty workspace name', () => {
    render(<CreateWorkspaceModal isOpen onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: 'Tạo Workspace' }));

    expect(screen.getByRole('alert')).toHaveTextContent('Tên Workspace không được để trống');
    expect(createWorkspace).not.toHaveBeenCalled();
  });

  it('trims the name, creates the workspace, and closes on success', async () => {
    const onClose = vi.fn();
    createWorkspace.mockResolvedValue({ id: 2 });
    render(<CreateWorkspaceModal isOpen onClose={onClose} />);

    fireEvent.change(screen.getByLabelText('Tên Workspace'), {
      target: { value: '  New Workspace  ' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Tạo Workspace' }));

    await waitFor(() => expect(createWorkspace).toHaveBeenCalledWith('New Workspace'));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('keeps the modal open and displays API errors', async () => {
    const onClose = vi.fn();
    createWorkspace.mockRejectedValue(new Error('Không thể tạo Workspace'));
    render(<CreateWorkspaceModal isOpen onClose={onClose} />);

    fireEvent.change(screen.getByLabelText('Tên Workspace'), { target: { value: 'Workspace' } });
    fireEvent.click(screen.getByRole('button', { name: 'Tạo Workspace' }));

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Không thể tạo Workspace'));
    expect(onClose).not.toHaveBeenCalled();
  });

  it('shows a loading state while creation is pending', async () => {
    let resolveCreation: ((value: { id: number }) => void) | undefined;
    createWorkspace.mockReturnValue(
      new Promise<{ id: number }>((resolve) => {
        resolveCreation = resolve;
      }),
    );
    render(<CreateWorkspaceModal isOpen onClose={vi.fn()} />);

    fireEvent.change(screen.getByLabelText('Tên Workspace'), { target: { value: 'Workspace' } });
    fireEvent.click(screen.getByRole('button', { name: 'Tạo Workspace' }));

    await waitFor(() => expect(screen.getByRole('button', { name: 'Đang tạo...' })).toBeDisabled());
    resolveCreation?.({ id: 2 });
  });
});
