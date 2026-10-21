import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { SettingsModal } from '@/components/modals/SettingsModal';

const { logout } = vi.hoisted(() => ({ logout: vi.fn() }));

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({
    user: { id: '1', name: 'Linh Tran', email: 'linh@example.com' },
    token: 'token',
    logout,
  }),
}));

vi.mock('@/context/ThemeContext', () => ({
  useTheme: () => ({ theme: 'light', toggleTheme: vi.fn() }),
}));

vi.mock('@/context/WorkspaceContext', () => ({
  useWorkspace: () => ({ role: 'data_lead' }),
}));

vi.mock('@/components/modals/AISettingsSection', () => ({
  AISettingsSection: () => <div>AI settings<input aria-label="AI draft" /></div>,
}));

describe('SettingsModal', () => {
  afterEach(() => { cleanup(); vi.clearAllMocks(); });

  it('displays the active workspace role instead of an Owner label', () => {
    render(<SettingsModal isOpen onClose={vi.fn()} />);

    expect(screen.getByText('Data Lead')).toBeInTheDocument();
    expect(screen.getByText('AI settings')).not.toBeVisible();
    expect(screen.queryByText('Owner')).not.toBeInTheDocument();
  });

  it('opens the AI tab and preserves unsaved input when switching tabs', () => {
    render(<SettingsModal isOpen onClose={vi.fn()} />);
    const general = screen.getByRole('tab', { name: 'Chung' });
    const ai = screen.getByRole('tab', { name: 'Nhà cung cấp & model AI' });
    expect(general).toHaveAttribute('aria-selected', 'true');
    fireEvent.click(ai);
    expect(ai).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tabpanel')).toHaveAttribute('id', ai.getAttribute('aria-controls'));
    expect(screen.getByText('Data Lead')).not.toBeVisible();
    fireEvent.change(screen.getByLabelText('AI draft'), { target: { value: 'unsaved-model' } });
    fireEvent.click(general);
    expect(screen.getByText('AI settings')).not.toBeVisible();
    fireEvent.click(ai);
    expect(screen.getByLabelText('AI draft')).toHaveValue('unsaved-model');
  });

  it('supports arrow keys, Home, and End with a single tab stop', () => {
    render(<SettingsModal isOpen onClose={vi.fn()} />);
    const general = screen.getByRole('tab', { name: 'Chung' });
    const ai = screen.getByRole('tab', { name: 'Nhà cung cấp & model AI' });
    general.focus();
    fireEvent.keyDown(general, { key: 'ArrowRight' });
    expect(ai).toHaveFocus();
    expect(general).toHaveAttribute('tabindex', '-1');
    fireEvent.keyDown(ai, { key: 'ArrowLeft' });
    expect(general).toHaveFocus();
    fireEvent.keyDown(general, { key: 'End' });
    expect(ai).toHaveFocus();
    fireEvent.keyDown(ai, { key: 'Home' });
    expect(general).toHaveFocus();
  });

  it('keeps account logout accessible from either tab and closes settings when logging out', () => {
    const onClose = vi.fn();
    render(<SettingsModal isOpen onClose={onClose} />);
    expect(screen.getByRole('button', { name: 'Đăng xuất tài khoản' })).toBeVisible();
    fireEvent.click(screen.getByRole('tab', { name: 'Nhà cung cấp & model AI' }));
    fireEvent.click(screen.getByRole('button', { name: 'Đăng xuất tài khoản' }));
    expect(onClose).toHaveBeenCalledOnce();
    expect(logout).toHaveBeenCalledOnce();
  });
});
