'use client';

import React from 'react';
import { Bot, History, LogOut, Moon, Settings2, ShieldCheck, Sun, Zap } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { useAuth } from '@/context/AuthContext';
import { useTheme } from '@/context/ThemeContext';
import { useWorkspace } from '@/context/WorkspaceContext';
import { LanguageSwitch } from '@/components/ui/language-switch';
import { useLanguage } from '@/context/LanguageContext';
import { Translated } from '@/components/ui/translated';
import { AISettingsSection } from '@/components/modals/AISettingsSection';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  databaseCount?: number;
  metricCount?: number;
  onOpenSyncLogs?: () => void;
}

const workspaceRoleLabels = {
  admin: 'Admin',
  data_lead: 'Data Lead',
  member: 'Member',
} as const;

export const SettingsModal: React.FC<SettingsModalProps> = ({
  isOpen,
  onClose,
  databaseCount = 1,
  metricCount = 0,
  onOpenSyncLogs,
}) => {
  const { user, token, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const { role } = useWorkspace();
  const { t } = useLanguage();
  const [activeTab, setActiveTab] = React.useState('general');
  const id = React.useId();
  const tabs = [
    { id: 'general', label: t('General', 'Chung'), icon: Settings2 },
    { id: 'ai', label: t('AI provider & model', 'Nhà cung cấp & model AI'), icon: Bot },
  ];

  function handleTabKeyDown(event: React.KeyboardEvent<HTMLButtonElement>, index: number) {
    const nextIndex = {
      ArrowRight: (index + 1) % tabs.length,
      ArrowLeft: (index + tabs.length - 1) % tabs.length,
      Home: 0,
      End: tabs.length - 1,
    }[event.key];
    if (nextIndex === undefined) return;
    event.preventDefault();
    setActiveTab(tabs[nextIndex].id);
    document.getElementById(`${id}-tab-${tabs[nextIndex].id}`)?.focus();
  }

  if (!isOpen) return null;

  const initials = user?.name
    ? user.name
        .split(' ')
        .map((n) => n[0])
        .join('')
        .toUpperCase()
        .slice(0, 2)
    : 'AI';

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] grid-cols-1 overflow-y-auto bg-background sm:max-w-4xl">
        <DialogHeader className="pr-8">
          <DialogTitle className="font-display text-2xl"><Translated text={"Settings"} /></DialogTitle>
          <DialogDescription>
            {t('Manage your account, appearance, and AI configuration.', 'Quản lý tài khoản, giao diện và cấu hình AI của bạn.')}
          </DialogDescription>
        </DialogHeader>

        <div role="tablist" aria-label={t('Settings sections', 'Các mục cài đặt')}
          className="grid min-w-0 grid-cols-[auto_1fr] gap-1 rounded-xl border border-border bg-secondary/40 p-1 sm:grid-cols-2">
          {tabs.map((tab, index) => (
            <button key={tab.id} type="button" role="tab" id={`${id}-tab-${tab.id}`}
              aria-controls={`${id}-panel-${tab.id}`} aria-selected={activeTab === tab.id}
              tabIndex={activeTab === tab.id ? 0 : -1}
              onClick={() => setActiveTab(tab.id)} onKeyDown={(event) => handleTabKeyDown(event, index)}
              className={`flex min-w-0 items-center justify-center gap-2 rounded-lg px-3 py-2.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:text-sm ${activeTab === tab.id ? 'bg-background text-foreground shadow-xs' : 'text-muted-foreground hover:bg-background/60 hover:text-foreground'}`}>
              <tab.icon className="h-4 w-4 shrink-0" aria-hidden="true" />
              <span>{tab.label}</span>
            </button>
          ))}
        </div>

        <div role="tabpanel" id={`${id}-panel-general`} aria-labelledby={`${id}-tab-general`}
          hidden={activeTab !== 'general'} tabIndex={0} className="min-w-0 text-xs">
          <div className="grid min-w-0 gap-4 py-2 sm:grid-cols-2">
            {/* Account Card */}
            <div className="flex items-center gap-3 rounded-lg border border-border bg-card p-4 shadow-2xs sm:col-span-2">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary font-mono text-sm font-bold text-primary-foreground">
                {initials}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-foreground">
                  {user?.name || 'Guest User'}
                </p>
                <p className="truncate font-mono text-[11px] text-muted-foreground">
                  {user?.email || 'guest@optimus.io'} <Translated text={"· Workspace member"} /></p>
              </div>
              <span className="shrink-0 rounded-full border border-border bg-secondary px-2.5 py-0.5 font-mono text-[10px] text-secondary-foreground">
                {role ? workspaceRoleLabels[role] : 'Chưa có vai trò'}
              </span>
            </div>

            {/* Appearance Switcher */}
            <div className="flex items-center justify-between rounded-lg border border-border bg-card p-3 shadow-2xs">
              <div className="flex items-center gap-3">
                {theme === 'dark' ? (
                  <Moon className="h-4 w-4 text-primary" />
                ) : (
                  <Sun className="h-4 w-4 text-amber-500" />
                )}
                <div>
                  <Label className="text-sm font-medium"><Translated text={"Appearance"} /></Label>
                  <p className="font-mono text-[11px] text-muted-foreground">
                    {theme === 'dark' ? t('Dark mode', 'Chế độ tối') : t('Light mode', 'Chế độ sáng')}
                  </p>
                </div>
              </div>
              <Switch
                checked={theme === 'dark'}
                onCheckedChange={toggleTheme}
                aria-label={t('Toggle dark mode', 'Bật hoặc tắt chế độ tối')}
              />
            </div>

            <div className="flex items-center justify-between rounded-lg border border-border bg-card p-3 shadow-2xs">
              <div>
                <Label className="text-sm font-medium">{t('Language', 'Ngôn ngữ')}</Label>
                <p className="font-mono text-[11px] text-muted-foreground">{t('Interface language', 'Ngôn ngữ giao diện')}</p>
              </div>
              <LanguageSwitch />
            </div>

            {/* Auto-Sync & Self-Healing Card */}
            <div className="rounded-lg border border-border bg-card p-3 shadow-2xs">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2">
                  <Zap className="h-4 w-4 shrink-0 text-amber-500" />
                  <Label className="text-sm font-medium"><Translated text={"Tự động đồng bộ & Tự vá schema"} /></Label>
                </div>
                <span className="flex items-center gap-1 font-mono text-[10px] font-semibold text-emerald-600 dark:text-emerald-400">
                  <ShieldCheck className="h-3.5 w-3.5" />
                  <Translated text={"Daily 02:00 AM"} />
                </span>
              </div>
              <p className="mt-1 font-mono text-[11px] text-muted-foreground">
                <Translated text={"Phát hiện thay đổi schema (đổi tên/thêm/xóa cột) & tự động viết lại AST metric formula."} />
              </p>
              {onOpenSyncLogs && (
                <div className="mt-2.5 pt-2 border-t border-border/50 flex justify-end">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      onClose();
                      onOpenSyncLogs();
                    }}
                    className="h-auto min-h-7 max-w-full whitespace-normal gap-1.5 font-mono text-[11px]"
                  >
                    <History className="h-3.5 w-3.5" />
                    <Translated text={"Xem lịch sử đồng bộ (Audit Logs)"} />
                  </Button>
                </div>
              )}
            </div>

            {/* Guardrails Card */}
            <div className="rounded-lg border border-border bg-card p-3 shadow-2xs">
              <div className="flex items-center justify-between">
                <Label className="text-sm font-medium"><Translated text={"Query guardrails"} /></Label>
                <span className="flex items-center gap-1 font-mono text-[10px] font-semibold text-emerald-600 dark:text-emerald-400">
                  <ShieldCheck className="h-3.5 w-3.5" />
                  <Translated text={"Active"} />
                </span>
              </div>
              <div className="mt-2 space-y-1.5 font-mono text-[11px] text-muted-foreground">
                <div className="flex items-center justify-between">
                  <span><Translated text={"Read-only enforcement"} /></span>
                  <span className="text-emerald-500 font-semibold"><Translated text={"Enabled"} /></span>
                </div>
                <div className="flex items-center justify-between">
                  <span><Translated text={"Row limit (default / max)"} /></span>
                  <span className="text-foreground">100 / 1.000</span>
                </div>
                <div className="flex items-center justify-between">
                  <span><Translated text={"Statement timeout"} /></span>
                  <span className="text-foreground"><Translated text={"15s"} /></span>
                </div>
              </div>
            </div>

            {/* Workspace Stats */}
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-lg border border-border bg-card p-3 shadow-2xs">
                <p className="font-display text-2xl text-foreground tabular-nums">{databaseCount}</p>
                <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                  <Translated text={"Data sources"} />
                </p>
              </div>
              <div className="rounded-lg border border-border bg-card p-3 shadow-2xs">
                <p className="font-display text-2xl text-foreground tabular-nums">{metricCount}</p>
                <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                  <Translated text={"Metrics"} />
                </p>
              </div>
            </div>

            {/* API Info */}
            <div className="rounded-lg border border-border bg-secondary/20 p-2.5 font-mono text-[10px] text-muted-foreground space-y-1">
              <div className="flex justify-between gap-3">
                <span><Translated text={"Engine:"} /></span>
                <span className="min-w-0 break-words text-right text-foreground font-semibold"><Translated text={"LangGraph + SemanticQueryCompiler"} /></span>
              </div>
              {token && (
                <div className="flex justify-between truncate">
                  <span><Translated text={"Token:"} /></span>
                  <span className="text-foreground truncate max-w-[200px]">{token.slice(0, 16)}...</span>
                </div>
              )}
            </div>
          </div>
        </div>
        <div role="tabpanel" id={`${id}-panel-ai`} aria-labelledby={`${id}-tab-ai`}
          hidden={activeTab !== 'ai'} tabIndex={0} className="min-w-0 py-2 text-xs">
          {user && token ? <AISettingsSection key={user.id} /> : (
            <p className="text-sm text-muted-foreground">{t('Sign in to configure your AI provider.', 'Đăng nhập để cấu hình nhà cung cấp AI.')}</p>
          )}
        </div>
        {user && (
          <div className="flex justify-end border-t border-border pt-4">
            <Button type="button" variant="outline" size="sm"
              className="gap-2 text-destructive hover:bg-destructive/10 hover:text-destructive"
              onClick={() => { onClose(); logout(); }}>
              <LogOut className="h-4 w-4" aria-hidden="true" />
              {t('Log out', 'Đăng xuất tài khoản')}
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
};
