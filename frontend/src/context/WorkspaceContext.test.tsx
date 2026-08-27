import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useWorkspace, WorkspaceProvider } from '@/context/WorkspaceContext';
import type { WorkspaceSummary } from '@/lib/api';

const authState = vi.hoisted(() => ({ token: 'token' as string | null }));
const apiMocks = vi.hoisted(() => ({
  listWorkspacesApi: vi.fn(),
  createWorkspaceApi: vi.fn(),
}));

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ token: authState.token }),
}));

vi.mock('@/lib/api', () => apiMocks);

function Probe() {
  const { currentWorkspace, role, permissions, workspaces, createWorkspace, reloadWorkspaces } =
    useWorkspace();
  const [error, setError] = React.useState('');
  return (
    <div>
      <span data-testid="workspace">{currentWorkspace?.name || 'none'}</span>
      <span data-testid="role">{role || 'none'}</span>
      <span data-testid="permissions">{Object.keys(permissions).length}</span>
      <span data-testid="count">{workspaces.length}</span>
      <span data-testid="error">{error}</span>
      <button
        type="button"
        onClick={() => void createWorkspace(' New Workspace ').catch((reason) => setError(reason.message))}
      >
        create
      </button>
      <button type="button" onClick={() => void reloadWorkspaces()}>
        reload
      </button>
    </div>
  );
}

const workspace = (id: number, name: string): WorkspaceSummary => ({
  id,
  name,
  slug: name.toLowerCase().replaceAll(' ', '-'),
  role: 'admin',
  permissions: { can_manage_members: true },
  created_at: '2026-01-01T00:00:00Z',
});

describe('WorkspaceProvider', () => {
  beforeEach(() => {
    authState.token = 'token';
    apiMocks.listWorkspacesApi.mockReset();
    apiMocks.createWorkspaceApi.mockReset();
    window.localStorage.clear();
  });

  afterEach(() => cleanup());

  it('creates a workspace, reloads, switches to it, and returns it', async () => {
    const initial = workspace(1, 'Initial Workspace');
    const created = workspace(2, 'New Workspace');
    apiMocks.listWorkspacesApi.mockResolvedValueOnce([initial]).mockResolvedValueOnce([initial, created]);
    apiMocks.createWorkspaceApi.mockResolvedValue(created);
    render(
      <WorkspaceProvider>
        <Probe />
      </WorkspaceProvider>,
    );

    await waitFor(() => expect(screen.getByTestId('workspace')).toHaveTextContent('Initial Workspace'));
    fireEvent.click(screen.getByRole('button', { name: 'create' }));

    await waitFor(() => expect(apiMocks.createWorkspaceApi).toHaveBeenCalledWith(' New Workspace '));
    await waitFor(() => expect(screen.getByTestId('workspace')).toHaveTextContent('New Workspace'));
    expect(window.localStorage.getItem('current_organization_id')).toBe('2');
  });

  it('clears the selected workspace when a reload returns an empty list', async () => {
    apiMocks.listWorkspacesApi.mockResolvedValueOnce([workspace(1, 'Existing')]).mockResolvedValueOnce([]);
    render(
      <WorkspaceProvider>
        <Probe />
      </WorkspaceProvider>,
    );

    await waitFor(() => expect(screen.getByTestId('workspace')).toHaveTextContent('Existing'));
    fireEvent.click(screen.getByRole('button', { name: 'reload' }));

    await waitFor(() => expect(screen.getByTestId('workspace')).toHaveTextContent('none'));
    expect(screen.getByTestId('role')).toHaveTextContent('none');
    expect(screen.getByTestId('permissions')).toHaveTextContent('0');
  });

  it('keeps the created workspace selected when the follow-up reload fails', async () => {
    const created = workspace(2, 'New Workspace');
    apiMocks.listWorkspacesApi.mockResolvedValueOnce([]).mockRejectedValueOnce(new Error('reload failed'));
    apiMocks.createWorkspaceApi.mockResolvedValue(created);
    render(
      <WorkspaceProvider>
        <Probe />
      </WorkspaceProvider>,
    );

    await waitFor(() => expect(screen.getByTestId('count')).toHaveTextContent('0'));
    fireEvent.click(screen.getByRole('button', { name: 'create' }));

    await waitFor(() => expect(screen.getByTestId('workspace')).toHaveTextContent('New Workspace'));
    expect(screen.getByTestId('error')).toHaveTextContent('');
  });

  it('ignores an old workspace response after the token is removed', async () => {
    let resolveOldRequest: ((items: WorkspaceSummary[]) => void) | undefined;
    apiMocks.listWorkspacesApi.mockReturnValueOnce(
      new Promise<WorkspaceSummary[]>((resolve) => {
        resolveOldRequest = resolve;
      }),
    );
    const view = render(
      <WorkspaceProvider>
        <Probe />
      </WorkspaceProvider>,
    );

    authState.token = null;
    view.rerender(
      <WorkspaceProvider>
        <Probe />
      </WorkspaceProvider>,
    );
    resolveOldRequest?.([workspace(1, 'Old User Workspace')]);

    await waitFor(() => expect(screen.getByTestId('count')).toHaveTextContent('0'));
    expect(screen.getByTestId('workspace')).toHaveTextContent('none');
  });

  it('does not call workspace APIs or retain state without a token', async () => {
    authState.token = null;
    render(
      <WorkspaceProvider>
        <Probe />
      </WorkspaceProvider>,
    );

    await waitFor(() => expect(screen.getByTestId('count')).toHaveTextContent('0'));
    expect(apiMocks.listWorkspacesApi).not.toHaveBeenCalled();
  });
});
