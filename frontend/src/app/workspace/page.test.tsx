import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import React from 'react';

import * as apiModule from '@/lib/api';
import WorkspacePage from './page';

beforeEach(() => {
  window.localStorage.clear();
  window.history.replaceState({}, '', '/workspace');
  vi.mocked(apiModule.listChatSessionsApi).mockResolvedValue([]);
});

const state = vi.hoisted(() => ({
  permissions: { can_manage_schema: false } as Record<string, boolean>,
}));

vi.mock('next/navigation', () => ({ useRouter: () => ({ replace: vi.fn() }) }));
vi.mock('next/dynamic', () => ({
  default: (loader: () => Promise<React.ComponentType<any>>) => {
    function DynamicMock(props: { isOpen?: boolean }) {
      const [Comp, setComp] = React.useState<React.ComponentType<any> | null>(null);
      React.useEffect(() => {
        let active = true;
        loader().then((mod) => {
          if (active) setComp(() => mod);
        });
        return () => {
          active = false;
        };
      }, []);
      if (!Comp) return null;
      return React.createElement(Comp, props);
    }
    return DynamicMock;
  },
}));
vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: { name: 'Tester' }, token: 'token', logout: vi.fn(), isLoading: false }),
}));
vi.mock('@/context/ThemeContext', () => ({
  useTheme: () => ({ theme: 'light', toggleTheme: vi.fn() }),
}));
vi.mock('@/context/WorkspaceContext', () => ({
  useWorkspace: () => ({
    currentWorkspace: { id: 1 },
    permissions: state.permissions,
  }),
}));
vi.mock('@/components/views/AIStudioView', () => ({ AIStudioView: () => null }));
vi.mock('@/components/views/ExportPlaygroundView', () => ({
  ExportPlaygroundView: () => <div data-testid="export-playground-view" />,
}));
vi.mock('@/components/views/MetricsCatalogView', () => ({
  MetricsCatalogView: (props: {
    metrics: apiModule.MetricRecord[];
    onApproveMetric?: (id: number) => Promise<void>;
    onApproveAll?: () => Promise<void>;
  }) => (
    <div>
      {props.metrics.map((metric) => (
        <div key={metric.metric_id}>
          {metric.has_pending_version ? 'review-pending' : `published-version-${metric.version}`}
          <button onClick={() => void props.onApproveMetric?.(metric.metric_id)}>catalog-approve-single</button>
        </div>
      ))}
      <button onClick={() => void props.onApproveAll?.()}>catalog-approve-all</button>
    </div>
  ),
}));
vi.mock('@/components/views/MetricsDashboardView', () => ({
  MetricsDashboardView: () => <div data-testid="metrics-dashboard-view" />,
}));
vi.mock('@/components/modals/ConnectDbModal', () => ({
  ConnectDbModal: () => <div data-testid="dynamic-modal" />,
}));
vi.mock('@/components/workspace/WorkspaceApp', () => ({
  WorkspaceApp: (props: {
    view?: string;
    activeDbId?: string | null;
    onConnectDatabase?: () => void;
    onRemoveDatabase?: (id: string) => void;
    onSelectView?: (view: string) => void;
    onSelectDatabase?: (id: string) => void;
    onSelectChatSession?: (id: string) => void;
    activeChatSessionId?: string | null;
    children: React.ReactNode;
  }) => (
    <div>
      <div data-testid="active-view">{props.view}</div>
      <div data-testid="active-database">{props.activeDbId}</div>
      <div data-testid="active-session">{props.activeChatSessionId}</div>
      <button onClick={() => props.onSelectDatabase?.('2')}>page-select-database-2</button>
      <button onClick={() => props.onSelectChatSession?.('older-chat')}>page-select-older-chat</button>
      {props.onConnectDatabase && <button onClick={props.onConnectDatabase}>page-connect</button>}
      {props.onRemoveDatabase && <button onClick={() => props.onRemoveDatabase?.('1')}>page-delete</button>}
      {props.onSelectView && (
        <button onClick={() => props.onSelectView?.('dashboard')}>page-nav-dashboard</button>
      )}
      {props.onSelectView && (
        <button onClick={() => props.onSelectView?.('export')}>page-nav-export</button>
      )}
      {props.onSelectView && (
        <button onClick={() => props.onSelectView?.('catalog')}>page-nav-catalog</button>
      )}
      {props.children}
    </div>
  ),
}));

describe('WorkspacePage tab persistence', () => {
  afterEach(() => {
    cleanup();
    window.localStorage.clear();
    state.permissions = { can_manage_schema: false };
    vi.mocked(apiModule.listLiveTargetDbs).mockResolvedValue([]);
  });

  it('opens Studio on a fresh visit and restores the last tab after reload', async () => {
    state.permissions = { can_use_chat: true, can_use_data_assistant: true };
    vi.mocked(apiModule.listLiveTargetDbs).mockResolvedValue([{
      id: 1, display_name: 'Test DB', dialect: 'postgresql', updated_at: '', created_at: '',
      semantic_db_id: 1, table_count: 1,
    }]);

    const first = render(<WorkspacePage />);
    await waitFor(() => expect(screen.getByTestId('active-view')).toHaveTextContent('ai-studio'));
    fireEvent.click(screen.getByText('page-nav-dashboard'));
    await waitFor(() => expect(window.localStorage.getItem('workspace_tab_1')).toBe('dashboard'));
    first.unmount();

    render(<WorkspacePage />);
    await waitFor(() => expect(screen.getByTestId('active-view')).toHaveTextContent('dashboard'));
  });

  it('restores an older conversation in the selected database after reload', async () => {
    state.permissions = { can_use_chat: true, can_use_data_assistant: true };
    vi.mocked(apiModule.listLiveTargetDbs).mockResolvedValue([1, 2].map((id) => ({
      id, display_name: `DB ${id}`, dialect: 'postgresql', updated_at: '', created_at: '',
      semantic_db_id: id, table_count: 1,
    })));
    vi.mocked(apiModule.listChatSessionsApi).mockImplementation(async (dbId) =>
      dbId === '2' ? [
        { id: 'newer-chat', title: 'Newest', created_at: '', updated_at: '' },
        { id: 'older-chat', title: 'Older', created_at: '', updated_at: '' },
      ] as apiModule.ChatSessionItem[] : [],
    );

    const first = render(<WorkspacePage />);
    await waitFor(() => expect(screen.getByTestId('active-database')).toHaveTextContent('1'));
    fireEvent.click(screen.getByText('page-select-database-2'));
    await waitFor(() => expect(apiModule.listChatSessionsApi).toHaveBeenCalledWith('2'));
    fireEvent.click(screen.getByText('page-select-older-chat'));
    expect(window.location.search).toBe('?chat=older-chat');
    first.unmount();

    render(<WorkspacePage />);
    await waitFor(() => expect(screen.getByTestId('active-database')).toHaveTextContent('2'));
    await waitFor(() => expect(screen.getByTestId('active-session')).toHaveTextContent('older-chat'));
  });
});
vi.mock('@/lib/api', () => ({
  approveMetricsApi: vi.fn(),
  approveSingleMetricApi: vi.fn(),
  convertRawSchemaToLayer: vi.fn().mockImplementation((...args: any[]) => ({
    id: String(args[0]),
    db_name: args[1],
    db_type: args[2],
    semantic_db_id: args[6],
    source_type: 'live',
    metrics: [],
    tables: [],
    table_count: 0,
    is_loaded: true,
  })),
  createMetricApi: vi.fn(),
  deleteChatSessionApi: vi.fn(),
  deleteDatabaseApi: vi.fn(),
  deleteLayer: vi.fn(),
  deleteMetricApi: vi.fn(),
  getImportedSchema: vi.fn(),
  getLiveTargetDb: vi.fn().mockResolvedValue({
    id: 1,
    display_name: 'Test DB',
    dialect: 'postgresql',
    raw_schema: 'CREATE TABLE orders (id INT);',
    updated_at: '',
    semantic_db_id: 1,
  }),
  getSemanticCatalogApi: vi.fn().mockResolvedValue({
    db_id: 1,
    source_type: 'live',
    query_supported: true,
    tables: [],
    relationships: [],
  }),
  listChatSessionsApi: vi.fn().mockResolvedValue([]),
  listImportedSchemas: vi.fn().mockResolvedValue([]),
  listLiveTargetDbs: vi.fn().mockResolvedValue([]),
  listMetricsApi: vi.fn().mockResolvedValue([]),
  listNotificationsApi: vi.fn().mockResolvedValue({ items: [], unread_count: 0 }),
  streamNotifications: vi.fn().mockReturnValue(() => {}),
  markNotificationsReadApi: vi.fn().mockResolvedValue(undefined),
  markNotificationReadApi: vi.fn().mockResolvedValue(undefined),
  METRIC_WRITE_PERMISSION_MESSAGE: 'forbidden',
  updateChatSessionTitleApi: vi.fn(),
  updateMetricApi: vi.fn(),
}));

describe('WorkspacePage metric approval sync', () => {
  afterEach(() => {
    cleanup();
    state.permissions = { can_manage_schema: false };
    vi.mocked(apiModule.listLiveTargetDbs).mockResolvedValue([]);
    vi.mocked(apiModule.listMetricsApi).mockResolvedValue([]);
  });

  it.each(['single', 'all'])('refreshes the published version after %s approval without reloading', async (mode) => {
    state.permissions = { can_manage_metrics: true, can_approve_metrics: true };
    vi.mocked(apiModule.listLiveTargetDbs).mockResolvedValue([{
      id: 1, display_name: 'Test DB', dialect: 'postgresql', updated_at: '', created_at: '',
      semantic_db_id: 1, table_count: 1,
    }]);
    const metric: apiModule.MetricRecord = {
      metric_id: 7, name: 'Revenue', definition: null, source: 'manual', created_at: '',
      status: 'approved', version: 1, has_pending_version: true,
    };
    const published = { ...metric, version: 2, has_pending_version: false };
    vi.mocked(apiModule.listMetricsApi).mockResolvedValue([metric]);
    vi.mocked(apiModule.approveSingleMetricApi).mockImplementation(async () => {
      vi.mocked(apiModule.listMetricsApi).mockResolvedValue([published]);
      return published;
    });
    vi.mocked(apiModule.approveMetricsApi).mockImplementation(async () => {
      vi.mocked(apiModule.listMetricsApi).mockResolvedValue([published]);
      return { approved_count: 1, message: 'Approved' };
    });

    render(<WorkspacePage />);
    expect(await screen.findByText('review-pending')).toBeInTheDocument();
    const catalogCalls = vi.mocked(apiModule.getSemanticCatalogApi).mock.calls.length;
    fireEvent.click(screen.getByText('page-nav-dashboard'));
    await waitFor(() => expect(apiModule.getSemanticCatalogApi).toHaveBeenCalledTimes(catalogCalls + 1));
    fireEvent.click(screen.getByText('page-nav-catalog'));
    expect(await screen.findByText('review-pending')).toBeInTheDocument();
    fireEvent.click(screen.getByText(`catalog-approve-${mode}`));

    expect(await screen.findByText('published-version-2')).toBeInTheDocument();
    expect(screen.queryByText('review-pending')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('page-nav-dashboard'));
    await waitFor(() => expect(apiModule.getSemanticCatalogApi).toHaveBeenCalledTimes(catalogCalls + 2));
  });
});

describe('WorkspacePage schema management', () => {
  afterEach(() => {
    cleanup();
    state.permissions = { can_manage_schema: false };
  });

  it.each(['admin', 'member'])('hides connection controls and callbacks for %s', async () => {
    render(<WorkspacePage />);

    await waitFor(() => expect(screen.queryByText('page-connect')).not.toBeInTheDocument());
    expect(screen.queryByText('page-delete')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Thêm kết nối Database' })).not.toBeInTheDocument();
  });

  it('exposes connection controls and callbacks to Data Lead', async () => {
    state.permissions = { can_manage_schema: true };
    render(<WorkspacePage />);

    fireEvent.click(await screen.findByText('page-connect'));
    expect(await screen.findByTestId('dynamic-modal')).toBeInTheDocument();
    expect(screen.getByText('page-delete')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Thêm kết nối Database' })).toBeInTheDocument();
  });
});

describe('WorkspacePage dashboard navigation', () => {
  afterEach(() => {
    cleanup();
    state.permissions = { can_manage_schema: false };
    vi.mocked(apiModule.listLiveTargetDbs).mockResolvedValue([]);
  });

  it('lazy-renders the Metrics Dashboard view when the dashboard tab is selected', async () => {
    vi.mocked(apiModule.listLiveTargetDbs).mockResolvedValue([
      {
        id: 1,
        display_name: 'Test DB',
        dialect: 'postgresql',
        updated_at: '',
        created_at: '',
        semantic_db_id: 1,
        table_count: 5,
      },
    ]);

    render(<WorkspacePage />);

    const dashboardNav = await screen.findByText('page-nav-dashboard');
    await waitFor(() => expect(window.localStorage.getItem('workspace_tab_1')).not.toBeNull());
    fireEvent.click(dashboardNav);

    const dashboardView = await screen.findByTestId('metrics-dashboard-view');
    expect(dashboardView).toBeInTheDocument();
  });
});

describe('WorkspacePage export guard', () => {
  afterEach(() => {
    cleanup();
    state.permissions = { can_manage_schema: false };
    vi.mocked(apiModule.listLiveTargetDbs).mockResolvedValue([]);
  });

  it('renders the Export Playground view for a role with can_export', async () => {
    state.permissions = { can_export: true };
    vi.mocked(apiModule.listLiveTargetDbs).mockResolvedValue([
      {
        id: 1,
        display_name: 'Test DB',
        dialect: 'postgresql',
        updated_at: '',
        created_at: '',
        semantic_db_id: 1,
        table_count: 5,
      },
    ]);

    render(<WorkspacePage />);

    const exportNav = await screen.findByText('page-nav-export');
    await waitFor(() => expect(window.localStorage.getItem('workspace_tab_1')).not.toBeNull());
    fireEvent.click(exportNav);

    const exportView = await screen.findByTestId('export-playground-view');
    expect(exportView).toBeInTheDocument();
  });

  it('does not render the Export Playground view without can_export', async () => {
    state.permissions = { can_export: false };
    vi.mocked(apiModule.listLiveTargetDbs).mockResolvedValue([
      {
        id: 1,
        display_name: 'Test DB',
        dialect: 'postgresql',
        updated_at: '',
        created_at: '',
        semantic_db_id: 1,
        table_count: 5,
      },
    ]);

    render(<WorkspacePage />);

    const exportNav = await screen.findByText('page-nav-export');
    fireEvent.click(exportNav);

    expect(screen.queryByTestId('export-playground-view')).not.toBeInTheDocument();
  });
});
