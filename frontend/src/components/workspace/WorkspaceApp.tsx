'use client';

import type { AppNotification, ChatSessionItem } from '@/lib/api';
import { cn } from '@/lib/utils';
import type { ViewId, WorkspaceDatabase } from '@/components/workspace/shared';
import { WorkspaceSidebar } from '@/components/workspace/WorkspaceSidebar';
import { useLanguage } from '@/context/LanguageContext';

interface WorkspaceAppProps {
  databases: WorkspaceDatabase[];
  activeDbId: string | null;
  view: ViewId;
  theme: 'light' | 'dark';
  pendingCount: number;
  pendingSchemaCount?: number;
  pendingDriftCount?: number;
  collapsed: boolean;
  userName?: string;
  chatSessions?: ChatSessionItem[];
  activeChatSessionId?: string | null;
  loadingChatSessions?: boolean;
  canChat?: boolean;
  chatMode?: 'data_assistant' | 'metric_studio';
  notifications?: AppNotification[];
  unreadNotifications?: number;
  onOpenCatalog?: (dbId?: number | null) => void;
  onOpenSchema?: (dbId?: number | null) => void;
  onMarkAllNotificationsRead?: () => Promise<void> | void;
  onMarkNotificationRead?: (item: AppNotification) => Promise<void> | void;
  onSelectView: (view: ViewId) => void;
  onToggleCollapse: () => void;
  onToggleTheme: () => void;
  onSelectDatabase: (id: string) => void;
  onRemoveDatabase?: (id: string) => void;
  onConnectDatabase?: () => void;
  onOpenSettings: () => void;
  onCreateWorkspace?: () => void;
  onOpenWorkspaceManagement?: () => void;
  onOpenSyncLogs?: () => void;
  onSelectChatSession?: (sessionId: string) => void;
  onNewChatSession?: () => void;
  onDeleteChatSession?: (sessionId: string) => void;
  onRenameChatSession?: (sessionId: string, newTitle: string) => Promise<void> | void;
  children: React.ReactNode;
}

export function WorkspaceApp({
  databases,
  activeDbId,
  view,
  theme,
  pendingCount,
  pendingSchemaCount,
  pendingDriftCount,
  collapsed,
  userName,
  chatSessions,
  activeChatSessionId,
  loadingChatSessions,
  canChat,
  chatMode,
  notifications,
  unreadNotifications,
  onOpenCatalog,
  onOpenSchema,
  onMarkAllNotificationsRead,
  onMarkNotificationRead,
  onSelectView,
  onToggleCollapse,
  onToggleTheme,
  onSelectDatabase,
  onRemoveDatabase,
  onConnectDatabase,
  onOpenSettings,
  onCreateWorkspace,
  onOpenWorkspaceManagement,
  onOpenSyncLogs,
  onSelectChatSession,
  onNewChatSession,
  onDeleteChatSession,
  onRenameChatSession,
  children,
}: WorkspaceAppProps) {
  const { translate } = useLanguage();
  return (
    <div
      role="region"
      aria-label={translate("Workspace")}
      className={cn(
        theme === 'dark' ? 'dark' : '',
        'fixed inset-0 flex h-dvh w-full overflow-hidden bg-background text-foreground',
      )}
    >
      <WorkspaceSidebar
        databases={databases}
        activeDbId={activeDbId}
        view={view}
        theme={theme}
        pendingCount={pendingCount}
        pendingSchemaCount={pendingSchemaCount}
        pendingDriftCount={pendingDriftCount}
        collapsed={collapsed}
        userName={userName}
        chatSessions={chatSessions}
        activeChatSessionId={activeChatSessionId}
        loadingChatSessions={loadingChatSessions}
        canChat={canChat}
        chatMode={chatMode}
        notifications={notifications}
        unreadNotifications={unreadNotifications}
        onOpenCatalog={onOpenCatalog}
        onOpenSchema={onOpenSchema}
        onMarkAllNotificationsRead={onMarkAllNotificationsRead}
        onMarkNotificationRead={onMarkNotificationRead}
        onSelectView={onSelectView}
        onToggleCollapse={onToggleCollapse}
        onToggleTheme={onToggleTheme}
        onSelectDatabase={onSelectDatabase}
        onRemoveDatabase={onRemoveDatabase}
        onConnectDatabase={onConnectDatabase}
        onOpenSettings={onOpenSettings}
        onCreateWorkspace={onCreateWorkspace}
        onOpenWorkspaceManagement={onOpenWorkspaceManagement}
        onOpenSyncLogs={onOpenSyncLogs}
        onSelectChatSession={onSelectChatSession}
        onNewChatSession={onNewChatSession}
        onDeleteChatSession={onDeleteChatSession}
        onRenameChatSession={onRenameChatSession}
      />
      <main className="flex min-w-0 flex-1 flex-col">{children}</main>
    </div>
  );
}
