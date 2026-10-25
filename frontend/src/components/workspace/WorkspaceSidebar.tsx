'use client';

import { useState, type ComponentType, type SVGProps } from 'react';
import {
  ChevronDown,
  ChevronLeft,
  Compass,
  History,
  PanelLeftClose,
  Plus,
  Trash2,
  Users,
} from 'lucide-react';

import type { AppNotification, ChatSessionItem } from '@/lib/api';
import { cn } from '@/lib/utils';
import { useWorkspace } from '@/context/WorkspaceContext';
import { useLanguage } from '@/context/LanguageContext';

import { ChatHistorySection } from './ChatHistorySection';
import { MoonAltToSunnyOutlineLoopTransitionIcon } from './MoonAltToSunnyOutlineLoopTransitionIcon';
import { Settings01Icon } from './Settings01Icon';
import { NotificationCenter } from './NotificationCenter';
import { EngineIcon, engineLabels, SectionLabel, type ViewId, type WorkspaceDatabase } from './shared';
import { Translated } from '@/components/ui/translated';
import { BotMessageSquareIcon } from '@/components/ui/BotMessageSquareIcon';
import { ClipboardDocumentListIcon } from '@/components/ui/ClipboardDocumentListIcon';
import { ChartBarSquareIcon } from '@/components/ui/ChartBarSquareIcon';
import { BuildingOffice2Icon } from '@/components/ui/BuildingOffice2Icon';
import { CircleStackIcon } from '@/components/ui/CircleStackIcon';
import { ArrowUpTrayIcon } from '@/components/ui/ArrowUpTrayIcon';
import { ArrowPathRoundedSquareIcon } from '@/components/ui/ArrowPathRoundedSquareIcon';
import { PlusIcon } from '@/components/ui/PlusIcon';

interface WorkspaceSidebarProps {
  databases: WorkspaceDatabase[];
  activeDbId: string | null;
  view: ViewId;
  theme: 'light' | 'dark';
  pendingCount: number;
  /** Table + column rows still awaiting BA/DA approval in the Metadata Store. */
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
  onOpenCatalog?: () => void;
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
}

const navItems: { id: ViewId; label: string; icon: ComponentType<SVGProps<SVGSVGElement>> }[] = [
  { id: 'ai-studio', label: 'AI Studio', icon: BotMessageSquareIcon },
  { id: 'schema', label: 'Schema Review', icon: CircleStackIcon },
  { id: 'catalog', label: 'Metrics Catalog', icon: ClipboardDocumentListIcon },
  { id: 'explorer', label: 'Metric Explorer', icon: Compass },
  { id: 'dashboard', label: 'Metrics Dashboard', icon: ChartBarSquareIcon },
  { id: 'export', label: 'Export Playground', icon: ArrowUpTrayIcon },
];

const vietnameseNavLabels: Record<ViewId, string> = {
  'ai-studio': 'AI Studio',
  schema: 'Duyệt cấu trúc',
  catalog: 'Danh mục chỉ số',
  explorer: 'Khám phá chỉ số',
  dashboard: 'Bảng điều khiển',
  export: 'Xuất dữ liệu',
};

export function WorkspaceSidebar({
  databases,
  activeDbId,
  view,
  theme,
  pendingCount,
  pendingSchemaCount = 0,
  pendingDriftCount = 0,
  collapsed,
  userName,
  chatSessions = [],
  activeChatSessionId = null,
  loadingChatSessions = false,
  canChat = false,
  chatMode = 'metric_studio',
  notifications = [],
  unreadNotifications = 0,
  onOpenCatalog,
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
}: WorkspaceSidebarProps) {
  const { t } = useLanguage();
  const { workspaces, currentWorkspace, role, permissions, isLoading, switchWorkspace } = useWorkspace();
  const [wsDropdownOpen, setWsDropdownOpen] = useState(false);
  const [sourcesExpanded, setSourcesExpanded] = useState(true);
  const canManageWorkspace = Boolean(
    permissions.can_manage_members || permissions.can_manage_invitations,
  );
  const canManageSchema = Boolean(permissions.can_manage_schema);
  const canExport = Boolean(permissions.can_export);
  const visibleNavItems = navItems.filter((item) => {
    if (item.id === 'ai-studio') return canChat;
    if (item.id === 'schema') return canManageSchema;
    if (item.id === 'export') return canExport;
    return true;
  });
  const getNavLabel = (id: ViewId, label: string) =>
    id === 'ai-studio' && chatMode === 'data_assistant'
      ? t('Data Assistant', 'Trợ lý dữ liệu')
      : t(label, vietnameseNavLabels[id]);

  if (collapsed) {
    return (
      <aside className="flex h-full w-14 flex-col items-center gap-4 border-r border-sidebar-border bg-sidebar py-4">
        <button
          type="button"
          onClick={onToggleCollapse}
          className="rounded-md p-2 text-sidebar-foreground/70 transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground cursor-pointer"
          aria-label={t('Expand sidebar', 'Mở rộng thanh bên')}
        >
          <ChevronLeft className="h-4 w-4 rotate-180" />
        </button>
        <NotificationCenter
          items={notifications}
          unreadCount={unreadNotifications}
          onOpenCatalog={onOpenCatalog}
          onMarkAllRead={onMarkAllNotificationsRead}
          onMarkRead={onMarkNotificationRead}
          align="left"
        />
        {canManageWorkspace && onOpenWorkspaceManagement && (
          <button
            type="button"
            onClick={onOpenWorkspaceManagement}
            className="rounded-md p-2 text-sidebar-foreground/70 transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground"
            title={t('Manage workspace and members', 'Quản lý Workspace & Thành viên')}
            aria-label={t('Manage workspace', 'Quản lý workspace')}
          >
            <BuildingOffice2Icon className="h-4 w-4" />
          </button>
        )}
        <nav className="flex flex-1 flex-col gap-1">
          {visibleNavItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => onSelectView(item.id)}
                aria-label={getNavLabel(item.id, item.label)}
                aria-current={view === item.id ? 'page' : undefined}
                className={cn(
                  'relative rounded-md p-2 transition-colors',
                  view === item.id
                    ? 'bg-sidebar-primary text-sidebar-primary-foreground'
                    : 'text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-foreground',
                )}
              >
                <Icon className="h-4 w-4" />
              </button>
            );
          })}
          {canManageSchema && onOpenSyncLogs && (
            <button
              type="button"
              onClick={onOpenSyncLogs}
              className="relative rounded-md p-2 text-amber-400/80 transition-colors hover:bg-sidebar-accent hover:text-amber-300 cursor-pointer"
              aria-label={t('Sync logs', 'Lịch sử đồng bộ')}
              title={pendingDriftCount > 0 ? t(`Sync logs (${pendingDriftCount} changes)`, `Lịch sử đồng bộ (${pendingDriftCount} thay đổi)`) : t('Sync logs', 'Lịch sử đồng bộ')}
            >
              <ArrowPathRoundedSquareIcon className="h-4 w-4" />
              {pendingDriftCount > 0 && (
                <span className="absolute -top-0.5 -right-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-amber-500 text-[9px] font-mono font-bold text-amber-950 shadow animate-pulse">
                  {pendingDriftCount}
                </span>
              )}
            </button>
          )}
          {canChat && (
            <button
              type="button"
              onClick={() => {
                onSelectView('ai-studio');
                onToggleCollapse();
              }}
              className="relative rounded-md p-2 text-sidebar-foreground/70 transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground cursor-pointer"
              aria-label={t('Open chat history', 'Mở lịch sử trò chuyện')}
              title={t('Open chat history', 'Mở lịch sử trò chuyện')}
            >
              <History className="h-4 w-4" />
              {chatSessions.length > 0 && (
                <span className="absolute -top-0.5 -right-0.5 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-sidebar-primary text-[9px] font-mono font-bold text-sidebar-primary-foreground">
                  {chatSessions.length}
                </span>
              )}
            </button>
          )}
        </nav>
        <div className="flex flex-col items-center gap-1">
          <button
            type="button"
            onClick={onToggleTheme}
            className="group flex h-8 w-8 items-center justify-center rounded-md text-sidebar-foreground/70 transition-colors hover:bg-sidebar-accent"
            aria-label={t('Toggle theme', 'Đổi giao diện sáng/tối')}
            title={t('Toggle theme', 'Đổi giao diện sáng/tối')}
          >
            <MoonAltToSunnyOutlineLoopTransitionIcon key={theme} theme={theme} size={16} />
          </button>
          <button
            type="button"
            onClick={onOpenSettings}
            className="group flex h-8 w-8 items-center justify-center rounded-md text-sidebar-foreground/70 transition-colors hover:bg-sidebar-accent"
            aria-label={t('Settings', 'Cài đặt')}
            title={t('Settings', 'Cài đặt')}
          >
            <Settings01Icon />
          </button>
        </div>
      </aside>
    );
  }

  return (
    <aside className="flex h-full w-72 flex-col border-r border-sidebar-border bg-sidebar">
      {/* Brand */}
      <div className="flex items-center justify-between px-4 py-4">
        <div className="flex items-baseline gap-1.5">
          <span className="font-display text-2xl tracking-tight text-sidebar-foreground">S206</span>
          <span className="font-mono text-[10px] text-sidebar-foreground/50">SEMANTIC</span>
        </div>
        <button
          type="button"
          onClick={onToggleCollapse}
          className="rounded-md p-1.5 text-sidebar-foreground/60 transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground cursor-pointer"
          aria-label={t('Collapse sidebar', 'Thu gọn thanh bên')}
        >
          <PanelLeftClose className="h-4 w-4" />
        </button>
      </div>

      {/* Workspace Switcher */}
      <div className="relative px-3 pb-2">
        <div className="workspace-switcher flex items-center gap-1.5 rounded-lg border border-sidebar-border bg-sidebar-accent/50 p-2">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-sidebar-primary text-sidebar-primary-foreground">
            <BuildingOffice2Icon className="h-3.5 w-3.5" />
          </div>
          <div
            className="min-w-0 flex-1 cursor-pointer"
            onClick={() => setWsDropdownOpen(!wsDropdownOpen)}
          >
            <p className="font-mono text-[10px] text-sidebar-foreground/50">Workspace</p>
            <div className="flex items-center gap-1">
              <span className="truncate text-xs font-semibold text-sidebar-foreground">
                {currentWorkspace?.name || 'Workspace'}
              </span>
              <ChevronDown className="h-3 w-3 shrink-0 text-sidebar-foreground/50" />
            </div>
          </div>
          {canManageWorkspace && onOpenWorkspaceManagement && (
            <button
              type="button"
              onClick={onOpenWorkspaceManagement}
              className="rounded p-1 text-sidebar-foreground/60 transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground cursor-pointer"
              title={t('Manage workspace and members', 'Quản lý Workspace & Thành viên')}
              aria-label={t('Manage workspace', 'Quản lý workspace')}
            >
              <Users className="h-3.5 w-3.5" />
            </button>
          )}
          <NotificationCenter
            items={notifications}
            unreadCount={unreadNotifications}
            onOpenCatalog={onOpenCatalog}
            onMarkAllRead={onMarkAllNotificationsRead}
            onMarkRead={onMarkNotificationRead}
            align="left"
          />
        </div>

        {wsDropdownOpen && (
          <div className="absolute left-3 right-3 top-full z-50 mt-1 rounded-lg border border-sidebar-border bg-card p-1 shadow-lg">
            <div className="flex items-center justify-between px-2 py-1">
              <p className="font-mono text-[10px] uppercase text-muted-foreground">
                {isLoading ? t('Loading workspaces...', 'Đang tải Workspace...') : workspaces.length ? t(`Workspaces (${workspaces.length})`, `Không gian làm việc (${workspaces.length})`) : t('No workspaces', 'Chưa có Workspace')}
              </p>
              {canManageWorkspace && onOpenWorkspaceManagement && (
                <button
                  type="button"
                  onClick={() => {
                    setWsDropdownOpen(false);
                    onOpenWorkspaceManagement();
                  }}
                  className="font-mono text-[10px] text-primary hover:underline cursor-pointer"
                >
                  <Translated text={"Quản lý"} />
                </button>
              )}
            </div>
            {workspaces.map((ws) => (
              <button
                key={ws.id}
                type="button"
                onClick={() => {
                  switchWorkspace(ws.id);
                  setWsDropdownOpen(false);
                }}
                className={cn(
                  'flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-xs transition-colors cursor-pointer',
                  ws.id === currentWorkspace?.id
                    ? 'bg-primary text-primary-foreground font-medium'
                    : 'text-foreground hover:bg-accent',
                )}
              >
                <span className="truncate">{ws.name}</span>
                <span className="font-mono text-[10px] opacity-75 capitalize">{ws.role}</span>
              </button>
            ))}
            <button
              type="button"
              onClick={() => {
                setWsDropdownOpen(false);
                onCreateWorkspace?.();
              }}
              className="mt-1 flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs text-primary transition-colors hover:bg-accent cursor-pointer"
            >
              <Plus className="h-3.5 w-3.5" />
              <Translated text={"Tạo Workspace mới"} />
            </button>
          </div>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex flex-col gap-0.5 px-3 py-2">
        {visibleNavItems.map((item) => {
          const Icon = item.icon;
          const active = view === item.id;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => onSelectView(item.id)}
              aria-current={active ? 'page' : undefined}
              className={cn(
                'group flex items-center gap-3 rounded-md px-3 py-2 text-left transition-colors',
                active
                  ? 'bg-sidebar-primary text-sidebar-primary-foreground'
                  : 'text-sidebar-foreground/75 hover:bg-sidebar-accent hover:text-sidebar-foreground',
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              <span className="flex-1 text-sm">{getNavLabel(item.id, item.label)}</span>
              {((item.id === 'catalog' && pendingCount > 0) ||
                (item.id === 'schema' && pendingSchemaCount > 0)) && (
                <span
                  className={cn(
                    'rounded-full px-1.5 py-0.5 font-mono text-[10px]',
                    active ? 'bg-sidebar-primary-foreground/20' : 'bg-sidebar-accent text-sidebar-foreground',
                  )}
                >
                  {item.id === 'schema' ? pendingSchemaCount : pendingCount}
                </span>
              )}
            </button>
          );
        })}
        {canManageSchema && onOpenSyncLogs && (
          <button
            type="button"
            onClick={onOpenSyncLogs}
            className={cn(
              'group flex items-center gap-3 rounded-md px-3 py-2 text-left transition-colors cursor-pointer',
              pendingDriftCount > 0
                ? 'bg-amber-500/10 text-amber-300 hover:bg-amber-500/15'
                : 'text-sidebar-foreground/75 hover:bg-sidebar-accent hover:text-sidebar-foreground',
            )}
          >
            <ArrowPathRoundedSquareIcon
              className={cn(
                'h-4 w-4 shrink-0',
                pendingDriftCount > 0 ? 'text-amber-400 animate-pulse' : 'text-amber-400',
              )}
            />
            <span className="flex-1 text-sm font-medium"><Translated text={"Sync Logs"} /></span>
            {pendingDriftCount > 0 && (
              <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-amber-500 px-1.5 font-mono text-[10px] font-bold text-amber-950 shadow-sm animate-pulse">
                {pendingDriftCount}
              </span>
            )}
          </button>
        )}
      </nav>

      {/* Chat History */}
      {canChat && (
        <ChatHistorySection
          sessions={chatSessions}
          activeSessionId={activeChatSessionId}
          loadingSessions={loadingChatSessions}
          canChat={canChat}
          onSelectSession={onSelectChatSession}
          onNewChat={onNewChatSession}
          onDeleteSession={onDeleteChatSession}
          onRenameSession={onRenameChatSession}
        />
      )}

      {/* Data Sources */}
      <div className={cn('flex min-h-0 flex-col px-3 pt-4', sourcesExpanded ? 'flex-1' : 'shrink-0')}>
        <div className="mb-2 flex items-center justify-between px-1">
          <button type="button" aria-expanded={sourcesExpanded} aria-controls="data-sources-list" onClick={() => setSourcesExpanded((open) => !open)} className="flex items-center gap-1.5 rounded px-1 py-1 text-left hover:bg-sidebar-accent cursor-pointer">
            <ChevronDown className={cn('h-3 w-3 text-sidebar-foreground/60 transition-transform', !sourcesExpanded && '-rotate-90')} />
            <SectionLabel><Translated text={"Data Sources"} /></SectionLabel>
          </button>
          {canManageSchema && onConnectDatabase && (
            <button
              type="button"
              onClick={onConnectDatabase}
              className="rounded p-1 text-sidebar-foreground/60 transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground cursor-pointer"
              aria-label={t('Connect database', 'Kết nối cơ sở dữ liệu')}
            >
              <PlusIcon className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
        <div id="data-sources-list" hidden={!sourcesExpanded} className={sourcesExpanded ? 'flex-1 space-y-1 overflow-y-auto pb-2' : undefined}>
          {databases.map((db) => {
            const active = db.id === activeDbId;
            return (
              <div
                key={db.id}
                data-active={active ? 'true' : 'false'}
                className={cn(
                  'group cursor-pointer rounded-md border px-3 py-2 transition-colors',
                  active
                    ? 'border-sidebar-border bg-sidebar-accent'
                    : 'border-transparent hover:bg-sidebar-accent/60',
                )}
                onClick={() => onSelectDatabase(db.id)}
              >
                <div className="flex items-center gap-2">
                  <span
                    data-testid="db-status-dot"
                    className={cn(
                      'h-1.5 w-1.5 shrink-0 rounded-full',
                      db.status === 'connected'
                        ? 'bg-emerald-500'
                        : db.status === 'error'
                          ? 'bg-destructive'
                          : 'bg-muted-foreground/50',
                    )}
                  />
                  <EngineIcon engine={db.engine} className="h-3.5 w-3.5 shrink-0 text-sidebar-foreground/60" />
                  <span className="flex-1 truncate font-mono text-[13px] text-sidebar-foreground">{db.name}</span>
                  {canManageSchema && onRemoveDatabase && databases.length > 1 && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        onRemoveDatabase(db.id);
                      }}
                      className="opacity-0 transition-opacity group-hover:opacity-100 cursor-pointer"
                      aria-label={t(`Remove ${db.name}`, `Xóa ${db.name}`)}
                    >
                      <Trash2 className="h-3.5 w-3.5 text-sidebar-foreground/50 hover:text-destructive" />
                    </button>
                  )}
                </div>
                <p className="mt-1 pl-[26px] font-mono text-[10px] text-sidebar-foreground/45">
                  {engineLabels[db.engine]} · {db.tables} {t('tables', 'bảng')}
                </p>
              </div>
            );
          })}
        </div>
      </div>

      {/* Footer */}
      <div className="mt-auto flex items-center justify-between gap-3 border-t border-sidebar-border px-4 py-3">
        <div className="min-w-0 flex-1">
          {userName && <p className="truncate text-sm font-semibold leading-5 text-sidebar-foreground">{userName}</p>}
          <p className="mt-1.5 flex w-fit max-w-full items-center gap-1.5 rounded-full border border-sidebar-border bg-sidebar-accent/60 px-2.5 py-0.5 text-[11px] leading-4">
            <span className="shrink-0 text-sidebar-foreground/60">{t('Role', 'Vai trò')}:</span>{' '}
            <span className="truncate font-semibold capitalize text-sidebar-foreground">{role ? role.replace('_', ' ') : t('No role', 'Chưa có vai trò')}</span>
          </p>
        </div>
        <div className="ml-auto flex shrink-0 items-center gap-1">
          <button
            type="button"
            onClick={onToggleTheme}
            className="flex h-8 w-8 items-center justify-center rounded-md text-sidebar-foreground/75 transition-colors hover:bg-sidebar-accent cursor-pointer"
            aria-label={t('Toggle theme', 'Đổi giao diện sáng/tối')}
            title={t('Toggle theme', 'Đổi giao diện sáng/tối')}
          >
            <MoonAltToSunnyOutlineLoopTransitionIcon key={theme} theme={theme} size={16} />
          </button>
          <button
            type="button"
            onClick={onOpenSettings}
            className="group flex h-8 w-8 items-center justify-center rounded-md text-sidebar-foreground/75 transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground cursor-pointer"
            aria-label={t('Settings', 'Cài đặt')}
            title={t('Settings', 'Cài đặt')}
          >
            <Settings01Icon />
          </button>
        </div>
      </div>
    </aside>
  );
}
