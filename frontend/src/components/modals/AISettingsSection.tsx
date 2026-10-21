'use client';

import { useEffect, useId, useState } from 'react';
import { Bot, Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useLanguage } from '@/context/LanguageContext';
import { getLLMSettingsApi, listLLMModelsApi, saveLLMSettingsApi, type LLMSettings } from '@/lib/api';

export function AISettingsSection() {
  const { t } = useLanguage();
  const id = useId();
  const [settings, setSettings] = useState<LLMSettings | null>(null);
  const [provider, setProvider] = useState('');
  const [model, setModel] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [models, setModels] = useState<string[]>([]);
  const [busy, setBusy] = useState<'initial' | 'models' | 'save' | null>('initial');
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let active = true;
    getLLMSettingsApi().then((data) => {
      if (!active) return;
      setSettings(data);
      const supported = data.providers.some((item) => item.id === data.provider);
      setProvider(supported ? data.provider : data.providers[0].id);
      setModel(supported ? data.model : '');
    }).catch((err) => {
      if (active) setError(err instanceof Error ? err.message : 'Could not load AI settings.');
    }).finally(() => { if (active) setBusy(null); });
    return () => { active = false; };
  }, []);

  const hasSavedKey = settings?.saved_models[provider] !== undefined;
  const canUseKey = Boolean(apiKey.trim() || hasSavedKey);

  async function loadModels() {
    setBusy('models');
    setError('');
    setSaved(false);
    try {
      const available = await listLLMModelsApi(provider, apiKey.trim());
      setModels(available);
      if (!available.length) setError(t('No models returned. Enter a model ID below.', 'Không tìm thấy model. Hãy nhập model ID bên dưới.'));
    } catch (err) {
      setError(err instanceof Error ? err.message : t('Could not load models.', 'Không thể tải model.'));
    } finally {
      setBusy(null);
    }
  }

  async function save() {
    setBusy('save');
    setError('');
    setSaved(false);
    try {
      const data = await saveLLMSettingsApi(provider, model.trim(), apiKey.trim());
      setSettings(data);
      setApiKey('');
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('Could not save AI settings.', 'Không thể lưu cấu hình AI.'));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="space-y-4 rounded-xl border border-border bg-card p-4 shadow-2xs sm:p-5" aria-labelledby={`${id}-title`}>
      <div className="flex items-center gap-2">
        <Bot className="h-4 w-4 text-primary" />
        <h3 id={`${id}-title`} className="text-sm font-medium">{t('AI provider & model', 'Nhà cung cấp & model AI')}</h3>
      </div>
      <p className="text-[11px] text-muted-foreground">
        {t('Applies to your account. API keys are encrypted on the server.', 'Áp dụng cho tài khoản của bạn. API key được mã hóa trên máy chủ.')}
      </p>
      {settings && (
        <div className="space-y-3 rounded-lg border border-primary/20 bg-primary/5 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h4 className="flex items-center gap-2 text-sm font-medium">
              <span className="h-2 w-2 rounded-full bg-primary" aria-hidden="true" />
              {t('Current AI configuration', 'Cấu hình AI đang sử dụng')}
            </h4>
            <span className="rounded-full border border-border bg-background px-2 py-1 text-[10px] text-muted-foreground">
              {settings.source === 'account' ? t('Your account', 'Tài khoản của bạn') : t('Server defaults', 'Cấu hình máy chủ')}
            </span>
          </div>
          <dl aria-label={t('Current AI configuration', 'Cấu hình AI đang sử dụng')} className="grid min-w-0 gap-3 sm:grid-cols-2">
            <div className="min-w-0">
              <dt className="text-[11px] text-muted-foreground">{t('Provider', 'Nhà cung cấp')}</dt>
              <dd className="mt-1 break-words text-sm font-semibold">
                {settings.providers.find((item) => item.id === settings.provider)?.name ?? settings.provider}
              </dd>
            </div>
            <div className="min-w-0">
              <dt className="text-[11px] text-muted-foreground">Model</dt>
              <dd className="mt-1 break-all font-mono text-sm font-medium">{settings.model || t('Not configured', 'Chưa cấu hình')}</dd>
            </div>
          </dl>
        </div>
      )}
      {busy === 'initial' && <p role="status">{t('Loading AI settings…', 'Đang tải cấu hình AI…')}</p>}
      {settings && (
        <fieldset disabled={busy !== null} className="grid min-w-0 gap-4 sm:grid-cols-2">
          {settings.source === 'environment' && <p className="text-[11px] text-muted-foreground sm:col-span-2">
            {t('Using server defaults. Save your own provider and key below.', 'Đang dùng cấu hình máy chủ. Lưu provider và key riêng bên dưới để thay đổi.')}
          </p>}
          <div className="min-w-0 space-y-1.5">
            <Label htmlFor={`${id}-provider`}>{t('Provider', 'Nhà cung cấp')}</Label>
            <select id={`${id}-provider`} value={provider} onChange={(event) => {
              const next = event.target.value;
              setProvider(next);
              setModel(settings.saved_models[next] ?? '');
              setApiKey('');
              setModels([]);
              setError('');
              setSaved(false);
            }} className="h-9 w-full min-w-0 rounded-md border border-input bg-background px-3 text-sm disabled:opacity-50">
              {settings.providers.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
          </div>
          <div className="min-w-0 space-y-1.5">
            <Label htmlFor={`${id}-key`}>API key</Label>
            <Input id={`${id}-key`} type="password" autoComplete="off" spellCheck={false} maxLength={4096}
              value={apiKey} onChange={(event) => { setApiKey(event.target.value); setSaved(false); setModels([]); }}
              placeholder={hasSavedKey ? t('Saved — leave blank to keep', 'Đã lưu — để trống để giữ key') : t('Enter provider API key', 'Nhập API key của provider')}
              aria-describedby={`${id}-key-help`} />
            <p id={`${id}-key-help`} className="text-[11px] text-muted-foreground">
              {hasSavedKey ? t('A key is saved for this provider.', 'Đã lưu key cho provider này.') : t('A key is required the first time you use each provider.', 'Cần nhập key khi sử dụng provider này lần đầu.')}
            </p>
          </div>
          <div className="min-w-0 space-y-1.5 sm:col-span-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Label htmlFor={`${id}-model`}>Model</Label>
              <Button type="button" size="sm" variant="outline" disabled={!canUseKey || busy !== null} onClick={loadModels}>
                {busy === 'models' && <Loader2 className="h-3 w-3 animate-spin" />}
                {t('Load models', 'Tải danh sách model')}
              </Button>
            </div>
            <Input id={`${id}-model`} list={`${id}-models`} value={model} maxLength={200} autoComplete="off"
              onChange={(event) => { setModel(event.target.value); setSaved(false); }}
              placeholder={t('Choose or enter a model ID', 'Chọn hoặc nhập model ID')} aria-describedby={`${id}-model-help`} />
            <datalist id={`${id}-models`}>{models.map((name) => <option key={name} value={name} />)}</datalist>
            <p id={`${id}-model-help`} className="text-[11px] text-muted-foreground">
              {t('Load models, then choose a chat model or enter its exact ID.', 'Tải danh sách rồi chọn model chat, hoặc nhập chính xác model ID.')}
            </p>
          </div>
          <div className="flex justify-end border-t border-border pt-4 sm:col-span-2">
            <Button type="button" size="sm" onClick={save} disabled={!canUseKey || !model.trim() || /\s/.test(model.trim()) || busy !== null}>
              {busy === 'save' && <Loader2 className="h-3 w-3 animate-spin" />}
              {t('Save AI settings', 'Lưu cấu hình AI')}
            </Button>
          </div>
        </fieldset>
      )}
      {error && <p role="alert" className="break-words text-destructive">{error}</p>}
      {saved && <p role="status" className="text-emerald-600 dark:text-emerald-400">
        {t('Saved. New AI requests will use this provider and model.', 'Đã lưu. Các yêu cầu AI tiếp theo sẽ dùng provider và model này.')}
      </p>}
    </section>
  );
}
