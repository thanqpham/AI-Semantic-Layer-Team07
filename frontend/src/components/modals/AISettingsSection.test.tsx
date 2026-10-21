import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AISettingsSection } from './AISettingsSection';
import { getLLMSettingsApi, listLLMModelsApi, saveLLMSettingsApi, type LLMSettings } from '@/lib/api';

vi.mock('@/lib/api', () => ({
  getLLMSettingsApi: vi.fn(),
  listLLMModelsApi: vi.fn(),
  saveLLMSettingsApi: vi.fn(),
}));

const settings: LLMSettings = {
  provider: 'openai', model: 'saved-model', source: 'account',
  saved_models: { openai: 'saved-model' },
  providers: [
    { id: 'openrouter', name: 'OpenRouter' },
    { id: 'gemini', name: 'Google Gemini' },
    { id: 'openai', name: 'OpenAI' },
    { id: 'anthropic', name: 'Anthropic (Claude)' },
    { id: 'deepseek', name: 'DeepSeek' },
  ],
};

describe('AISettingsSection', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(getLLMSettingsApi).mockResolvedValue(settings);
    vi.mocked(listLLMModelsApi).mockResolvedValue(['chat-one', 'chat-two']);
    vi.mocked(saveLLMSettingsApi).mockResolvedValue(settings);
  });
  afterEach(cleanup);

  it('shows provider choices and reuses the saved key when changing models', async () => {
    render(<AISettingsSection />);
    const model = await screen.findByLabelText('Model');
    expect(screen.getAllByRole('option')).toHaveLength(5);
    expect(screen.getByLabelText('API key')).toHaveValue('');
    expect(screen.getByLabelText('API key')).toHaveAttribute('type', 'password');
    fireEvent.change(model, { target: { value: 'new-model' } });
    fireEvent.click(screen.getByRole('button', { name: 'Lưu cấu hình AI' }));
    await waitFor(() => expect(saveLLMSettingsApi).toHaveBeenCalledWith('openai', 'new-model', ''));
    expect(await screen.findByRole('status')).toHaveTextContent('Đã lưu');
  });

  it('clears the typed key when changing provider and restores the saved model', async () => {
    render(<AISettingsSection />);
    const provider = await screen.findByLabelText('Nhà cung cấp');
    fireEvent.change(screen.getByLabelText('API key'), { target: { value: 'unsaved-openai-key' } });
    fireEvent.change(provider, { target: { value: 'deepseek' } });
    expect(screen.getByLabelText('API key')).toHaveValue('');
    expect(screen.getByLabelText('Model')).toHaveValue('');
    fireEvent.change(screen.getByLabelText('Model'), { target: { value: 'deepseek-chat' } });
    expect(screen.getByRole('button', { name: 'Lưu cấu hình AI' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('API key'), { target: { value: 'deepseek-key' } });
    fireEvent.click(screen.getByRole('button', { name: 'Lưu cấu hình AI' }));
    await waitFor(() => expect(saveLLMSettingsApi).toHaveBeenCalledWith('deepseek', 'deepseek-chat', 'deepseek-key'));
    expect(screen.getByLabelText('API key')).toHaveValue('');
    fireEvent.change(provider, { target: { value: 'openai' } });
    expect(screen.getByLabelText('Model')).toHaveValue('saved-model');
  });

  it('loads models from the selected provider without saving the key', async () => {
    render(<AISettingsSection />);
    await screen.findByLabelText('Model');
    fireEvent.click(screen.getByRole('button', { name: 'Tải danh sách model' }));
    await waitFor(() => expect(listLLMModelsApi).toHaveBeenCalledWith('openai', ''));
    await waitFor(() => expect(document.querySelector('datalist option[value="chat-two"]')).toBeInTheDocument());
    expect(saveLLMSettingsApi).not.toHaveBeenCalled();
  });

  it('reports save failure and keeps the entered key for retry', async () => {
    vi.mocked(saveLLMSettingsApi).mockRejectedValue(new Error('Server unavailable'));
    render(<AISettingsSection />);
    await screen.findByLabelText('Model');
    fireEvent.change(screen.getByLabelText('API key'), { target: { value: 'replacement-key' } });
    fireEvent.click(screen.getByRole('button', { name: 'Lưu cấu hình AI' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Server unavailable');
    expect(screen.getByLabelText('API key')).toHaveValue('replacement-key');
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('reports initial load failure without allowing an accidental overwrite', async () => {
    vi.mocked(getLLMSettingsApi).mockRejectedValue(new Error('Cannot load settings'));
    render(<AISettingsSection />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Cannot load settings');
    expect(screen.queryByRole('button', { name: 'Lưu cấu hình AI' })).not.toBeInTheDocument();
  });

  it('keeps the active provider and model until a new configuration is saved', async () => {
    vi.mocked(saveLLMSettingsApi).mockResolvedValue({
      ...settings, provider: 'deepseek', model: 'deepseek-chat',
      saved_models: { ...settings.saved_models, deepseek: 'deepseek-chat' },
    });
    render(<AISettingsSection />);
    const summary = within(await screen.findByLabelText('Cấu hình AI đang sử dụng'));
    expect(summary.getByText('OpenAI')).toBeInTheDocument();
    expect(summary.getByText('saved-model')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Nhà cung cấp'), { target: { value: 'deepseek' } });
    fireEvent.change(screen.getByLabelText('Model'), { target: { value: 'deepseek-chat' } });
    fireEvent.change(screen.getByLabelText('API key'), { target: { value: 'new-key' } });
    expect(summary.getByText('OpenAI')).toBeInTheDocument();
    expect(summary.queryByText('deepseek-chat')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Lưu cấu hình AI' }));
    expect(await summary.findByText('DeepSeek')).toBeInTheDocument();
    expect(summary.getByText('deepseek-chat')).toBeInTheDocument();
    expect(summary.queryByText('saved-model')).not.toBeInTheDocument();
  });

  it('shows server configuration even when its provider is not in the picker', async () => {
    vi.mocked(getLLMSettingsApi).mockResolvedValue({
      ...settings, source: 'environment', provider: 'custom-provider', model: 'server-model', saved_models: {},
    });
    render(<AISettingsSection />);
    const summary = within(await screen.findByLabelText('Cấu hình AI đang sử dụng'));
    expect(summary.getByText('custom-provider')).toBeInTheDocument();
    expect(summary.getByText('server-model')).toBeInTheDocument();
    expect(screen.getByText('Cấu hình máy chủ')).toBeInTheDocument();
  });
});
