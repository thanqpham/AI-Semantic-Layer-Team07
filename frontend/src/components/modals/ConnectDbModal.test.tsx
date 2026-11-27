import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ConnectDbModal } from '@/components/modals/ConnectDbModal';

const connectMock = vi.fn();

vi.mock('@/context/AuthContext', () => ({ useAuth: () => ({ token: null }) }));
vi.mock('@/lib/jwt', () => ({ getStoredToken: () => 'stored-access-token' }));
vi.mock('@/lib/api', () => ({
  connectLiveTargetDb: (...args: unknown[]) => connectMock(...args),
  uploadSqlDumpPreview: vi.fn(),
  saveImportedSchema: vi.fn(),
  updateLayer: vi.fn(),
  convertRawSchemaToLayer: () => ({ id: '9', db_name: 'Sales', db_type: 'postgresql', status: 'Draft', updated_at: '', tables: [], metrics: [], semantic_db_id: 12, source_type: 'live' }),
}));

describe('ConnectDbModal authentication', () => {
  afterEach(() => cleanup());

  beforeEach(() => {
    connectMock.mockReset();
    connectMock.mockResolvedValue({ id: 9, display_name: 'Sales', dialect: 'postgresql', raw_schema: { tables: [] }, updated_at: '', semantic_db_id: 12 });
  });

  it('uses a persisted access token while AuthContext is still hydrating', async () => {
    render(<ConnectDbModal isOpen onClose={vi.fn()} onSuccess={vi.fn()} />);
    fireEvent.change(screen.getByPlaceholderText('VD: CSDL bán hàng (Production)'), { target: { value: 'Sales' } });
    fireEvent.change(screen.getByPlaceholderText(/localhost:5432/), { target: { value: 'postgresql://localhost:5432/sales' } });
    fireEvent.click(screen.getByText('Bắt Đầu Kết Nối & Introspect'));
    await waitFor(() => expect(connectMock).toHaveBeenCalledWith('Sales', 'auto', 'postgresql://localhost:5432/sales', 'stored-access-token'));
    expect(screen.queryByText(/Vui lòng đăng nhập/)).not.toBeInTheDocument();
  });
});

describe('ConnectDbModal guardrail copy', () => {
  afterEach(() => cleanup());

  it('renders the exact guardrail safety constraints', () => {
    render(<ConnectDbModal isOpen onClose={vi.fn()} onSuccess={vi.fn()} />);
    expect(screen.getByText(/Chỉ dành cho Live DB/)).toBeInTheDocument();
    expect(screen.getByText(/SELECT-only/)).toBeInTheDocument();
    expect(screen.getByText(/Mặc định 100 dòng/)).toBeInTheDocument();
    expect(screen.getByText(/Tối đa 1\.000 dòng/)).toBeInTheDocument();
    expect(screen.getByText(/Timeout 15 giây/)).toBeInTheDocument();
  });
});

describe('ConnectDbModal credential split', () => {
  afterEach(() => cleanup());
  beforeEach(() => { connectMock.mockReset(); connectMock.mockResolvedValue({ id: 9, display_name: 'Sales', dialect: 'postgresql', raw_schema: { tables: [] }, updated_at: '', semantic_db_id: 12 }); });

  it('sends dbUser/dbPassword separately and masks the password input', async () => {
    render(<ConnectDbModal isOpen onClose={vi.fn()} onSuccess={vi.fn()} />);
    fireEvent.change(screen.getByPlaceholderText('VD: CSDL bán hàng (Production)'), { target: { value: 'Sales' } });
    fireEvent.change(screen.getByPlaceholderText(/localhost:5432/), { target: { value: 'postgresql://localhost:5432/analytics' } });
    fireEvent.change(screen.getByPlaceholderText('Ví dụ: semantic_reader'), { target: { value: 'semantic_reader' } });
    fireEvent.change(screen.getByPlaceholderText('Nhập mật khẩu'), { target: { value: 'pw@ss:1' } });
    expect(screen.getByPlaceholderText('Nhập mật khẩu')).toHaveProperty('type', 'password');
    fireEvent.click(screen.getByText('Bắt Đầu Kết Nối & Introspect'));
    await waitFor(() => expect(connectMock).toHaveBeenCalledWith('Sales', 'auto', 'postgresql://localhost:5432/analytics', 'stored-access-token', { dbUser: 'semantic_reader', dbPassword: 'pw@ss:1' }));
  });

  it('requires user and password together', async () => {
    render(<ConnectDbModal isOpen onClose={vi.fn()} onSuccess={vi.fn()} />);
    fireEvent.change(screen.getByPlaceholderText('VD: CSDL bán hàng (Production)'), { target: { value: 'Sales' } });
    fireEvent.change(screen.getByPlaceholderText(/localhost:5432/), { target: { value: 'postgresql://localhost:5432/analytics' } });
    fireEvent.change(screen.getByPlaceholderText('Ví dụ: semantic_reader'), { target: { value: 'semantic_reader' } });
    fireEvent.click(screen.getByText('Bắt Đầu Kết Nối & Introspect'));
    expect(await screen.findByText('User và password phải đi cùng nhau')).toBeInTheDocument();
    expect(connectMock).not.toHaveBeenCalled();
  });

  it('rejects a URL that embeds credentials', async () => {
    render(<ConnectDbModal isOpen onClose={vi.fn()} onSuccess={vi.fn()} />);
    fireEvent.change(screen.getByPlaceholderText('VD: CSDL bán hàng (Production)'), { target: { value: 'Sales' } });
    fireEvent.change(screen.getByPlaceholderText(/localhost:5432/), { target: { value: 'postgresql://semantic_reader:reader123@localhost:5432/demo_shop' } });
    fireEvent.click(screen.getByText('Bắt Đầu Kết Nối & Introspect'));
    expect(await screen.findByText('URL không được chứa user/password - nhập vào ô Tên đăng nhập và Mật khẩu bên dưới')).toBeInTheDocument();
    expect(connectMock).not.toHaveBeenCalled();
  });
});
