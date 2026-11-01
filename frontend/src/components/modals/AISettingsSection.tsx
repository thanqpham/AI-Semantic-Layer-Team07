'use client';

import { useEffect, useId, useMemo, useState } from 'react';
import { Activity, Bot, Check, ChevronDown, Loader2, RotateCcw, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useLanguage } from '@/context/LanguageContext';
import { clearLLMUsageApi, getLLMSettingsApi, listLLMModelsApi, saveLLMSettingsApi, type LLMSettings } from '@/lib/api';

const PROVIDER_HINTS: Record<string, { badge: string; hintEn: string; hintVi: string }> = {
  openrouter: { badge: 'Multi-Model Router', hintEn: 'Access 300+ models via unified OpenRouter endpoint', hintVi: 'Truy cập 300+ model qua cổng hợp nhất OpenRouter' },
  gemini: { badge: 'Google AI', hintEn: 'Gemini 2.5 Pro / Flash via Google AI Studio', hintVi: 'Gemini 2.5 Pro / Flash qua Google AI Studio' },
  openai: { badge: 'Official API', hintEn: 'GPT-4.1, GPT-4o, o3 / o4-mini series', hintVi: 'Dòng model GPT-4.1, GPT-4o, o3 / o4-mini' },
  anthropic: { badge: 'Native Messages', hintEn: 'Claude 4 / 3.7 Sonnet & Haiku via Anthropic API', hintVi: 'Claude 4 / 3.7 Sonnet & Haiku qua Anthropic API' },
  deepseek: { badge: 'Reasoning & Chat', hintEn: 'DeepSeek-V3 (deepseek-chat) & R1 (deepseek-reasoner)', hintVi: 'DeepSeek-V3 (deepseek-chat) & R1 (deepseek-reasoner)' },
  groq: { badge: 'LPU Ultra-Fast', hintEn: 'High-speed Llama, Qwen & DeepSeek on Groq LPU', hintVi: 'Tốc độ siêu nhanh cho Llama, Qwen & DeepSeek trên Groq' },
  mimo: { badge: 'Xiaomi MiMo', hintEn: 'Xiaomi MiMo reasoning & chat models', hintVi: 'Các model suy luận và chat Xiaomi MiMo' },
  mistral: { badge: 'Mistral La Plateforme', hintEn: 'Mistral Large, Small, Codestral & Pixtral', hintVi: 'Mistral Large, Small, Codestral & Pixtral' },
  xai: { badge: 'Grok API', hintEn: 'xAI Grok-3 & Grok-2 models', hintVi: 'Các model xAI Grok-3 & Grok-2' },
  together: { badge: 'Open-Weights Cloud', hintEn: 'Llama, Qwen, DeepSeek & Mixtral on Together AI', hintVi: 'Llama, Qwen, DeepSeek & Mixtral trên Together AI' },
  fireworks: { badge: 'Fast Inference', hintEn: 'Production-grade open models on Fireworks AI', hintVi: 'Chạy các model mã nguồn mở tốc độ cao trên Fireworks AI' },
  perplexity: { badge: 'Sonar API', hintEn: 'Sonar Pro & Reasoning models', hintVi: 'Các model Sonar Pro & Reasoning' },
  cerebras: { badge: 'Wafer-Scale Inference', hintEn: 'Ultra-low latency Llama & Qwen inference', hintVi: 'Suy luận độ trễ cực thấp cho Llama & Qwen' },
  qwen: { badge: 'Alibaba DashScope', hintEn: 'Qwen-Max, Qwen-Plus, Qwen-Turbo & QwQ', hintVi: 'Qwen-Max, Qwen-Plus, Qwen-Turbo & QwQ' },
    moonshot: { badge: 'Kimi API', hintEn: 'Moonshot Kimi K2 & long-context v1 models', hintVi: 'Moonshot Kimi K2 & các model ngữ cảnh dài v1' },
  cohere: { badge: 'Enterprise AI', hintEn: 'Command A & Command R+ models', hintVi: 'Dòng model Command A & Command R+' },
  glm: { badge: 'Zhipu AI', hintEn: 'GLM-4-Plus, GLM-4-Air, GLM-4-Flash & GLM-4V', hintVi: 'GLM-4-Plus, GLM-4-Air, GLM-4-Flash & GLM-4V' },
};

export function AISettingsSection() {
  const { t } = useLanguage();
  const id = useId();
  const [settings, setSettings] = useState<LLMSettings | null>(null);
  const [provider, setProvider] = useState('');
  const [model, setModel] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [models, setModels] = useState<string[]>([]);
    const [modelListOpen, setModelListOpen] = useState(false);
  const [filterByInput, setFilterByInput] = useState(false);
  const [busy, setBusy] = useState<'initial' | 'models' | 'save' | 'reset-usage' | null>('initial');
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
  const providerMeta = PROVIDER_HINTS[provider];

  const visibleModels = useMemo(() => {
    if (!filterByInput) return models;
    const query = model.trim().toLowerCase();
    if (!query) return models;
    const matched = models.filter((name) => name.toLowerCase().includes(query));
    return matched.length > 0 ? matched : models;
  }, [models, model, filterByInput]);

  async function loadModels() {
    setBusy('models');
    setError('');
    setSaved(false);
    try {
      const available = await listLLMModelsApi(provider, apiKey.trim());
      setModels(available);
      setFilterByInput(false);
      setModelListOpen(available.length > 0);
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
      setModelListOpen(false);
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('Could not save AI settings.', 'Không thể lưu cấu hình AI.'));
    } finally {
      setBusy(null);
    }
  }

  async function resetUsage() {
    setBusy('reset-usage');
    setError('');
    try {
      const data = await clearLLMUsageApi();
      setSettings(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('Could not reset AI usage.', 'Không thể đặt lại thống kê sử dụng AI.'));
    } finally {
      setBusy(null);
    }
  }

  const usage = settings?.usage ?? {
    total_requests: 0,
    input_tokens: 0,
    output_tokens: 0,
    total_tokens: 0,
    cached_input_tokens: 0,
    reasoning_tokens: 0,
    last_used_at: null,
    by_provider: [],
  };

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
      {settings && (
        <div
          aria-label={t('AI Usage Statistics', 'Thống kê sử dụng AI')}
          className="space-y-3 rounded-lg border border-border bg-secondary/20 p-4"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Activity className="h-3.5 w-3.5 text-primary" />
              <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                {t('AI Token & Request Usage', 'Thống kê Token & Yêu cầu AI')}
              </h4>
            </div>
            {usage.total_requests > 0 && (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                disabled={busy !== null}
                onClick={resetUsage}
                className="h-6 px-2 text-[11px] text-muted-foreground hover:text-foreground"
              >
                {busy === 'reset-usage' ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <RotateCcw className="h-3 w-3" />
                )}
                {t('Reset usage', 'Đặt lại thống kê')}
              </Button>
            )}
          </div>
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
            <div className="rounded-md border border-border/70 bg-background/80 p-2.5">
              <p className="text-[10px] text-muted-foreground">{t('Requests', 'Số lượt gọi')}</p>
              <p className="mt-0.5 font-mono text-sm font-semibold">{usage.total_requests.toLocaleString()}</p>
            </div>
            <div className="rounded-md border border-border/70 bg-background/80 p-2.5">
              <p className="text-[10px] text-muted-foreground">{t('Input tokens', 'Token đầu vào')}</p>
              <p className="mt-0.5 font-mono text-sm font-semibold">{usage.input_tokens.toLocaleString()}</p>
            </div>
            <div className="rounded-md border border-border/70 bg-background/80 p-2.5">
              <p className="text-[10px] text-muted-foreground">{t('Output tokens', 'Token đầu ra')}</p>
              <p className="mt-0.5 font-mono text-sm font-semibold">{usage.output_tokens.toLocaleString()}</p>
            </div>
            <div className="rounded-md border border-primary/25 bg-primary/5 p-2.5">
              <p className="text-[10px] font-medium text-primary">{t('Total tokens', 'Tổng token')}</p>
              <p className="mt-0.5 font-mono text-sm font-bold text-primary">{usage.total_tokens.toLocaleString()}</p>
            </div>
          </div>
          {(usage.cached_input_tokens > 0 || usage.reasoning_tokens > 0) && (
            <div className="flex flex-wrap gap-3 text-[11px] text-muted-foreground">
              {usage.cached_input_tokens > 0 && (
                <span>
                  {t('Cached input:', 'Token bộ nhớ đệm:')}{' '}
                  <strong className="font-mono text-foreground">{usage.cached_input_tokens.toLocaleString()}</strong>
                </span>
              )}
              {usage.reasoning_tokens > 0 && (
                <span>
                  {t('Reasoning tokens:', 'Token suy luận:')}{' '}
                  <strong className="font-mono text-foreground">{usage.reasoning_tokens.toLocaleString()}</strong>
                </span>
              )}
            </div>
          )}
          {usage.by_provider.length > 0 && (
            <div className="space-y-1.5 border-t border-border/60 pt-2.5">
              <p className="text-[10px] font-medium text-muted-foreground">
                {t('Breakdown by provider', 'Chi tiết theo nhà cung cấp')}
              </p>
              <div className="space-y-1">
                {usage.by_provider.map((item) => {
                  const providerLabel = settings.providers.find((p) => p.id === item.provider)?.name ?? item.provider;
                  return (
                    <div
                      key={item.provider}
                      className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border/50 bg-background/60 px-2.5 py-1.5 text-xs"
                    >
                      <div className="flex min-w-0 items-center gap-2">
                        <span className="font-medium">{providerLabel}</span>
                        {item.last_model && (
                          <span className="truncate rounded bg-secondary px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                            {item.last_model}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-3 font-mono text-[11px] text-muted-foreground">
                        <span>
                          {item.requests} {t('req', 'lượt')}
                        </span>
                        <span className="font-semibold text-foreground">
                          {item.total_tokens.toLocaleString()} tok
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}
      {busy === 'initial' && <p role="status">{t('Loading AI settings…', 'Đang tải cấu hình AI…')}</p>}
      {settings && (
        <fieldset disabled={busy !== null} className="grid min-w-0 gap-4 sm:grid-cols-2">
          {settings.source === 'environment' && <p className="text-[11px] text-muted-foreground sm:col-span-2">
            {t('Using server defaults. Save your own provider and key below.', 'Đang dùng cấu hình máy chủ. Lưu provider và key riêng bên dưới để thay đổi.')}
          </p>}
                    <div className="min-w-0 space-y-1.5">
            <div className="flex min-h-[22px] items-center justify-between gap-2">
              <Label htmlFor={`${id}-provider`}>{t('Provider', 'Nhà cung cấp')}</Label>
              <span className="truncate rounded-full border border-border bg-secondary/60 px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
                {providerMeta?.badge ?? 'AI Provider'}
              </span>
            </div>
            <select id={`${id}-provider`} value={provider} onChange={(event) => {
              const next = event.target.value;
              setProvider(next);
              setModel(settings.saved_models[next] ?? '');
              setApiKey('');
              setModels([]);
              setModelListOpen(false);
              setFilterByInput(false);
              setError('');
              setSaved(false);
            }} className="h-9 w-full min-w-0 rounded-md border border-input bg-background px-3 text-sm disabled:opacity-50">
              {settings.providers.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}{settings.saved_models[item.id] ? ' ✓' : ''}
                </option>
              ))}
            </select>
            <p className="min-h-[32px] line-clamp-2 text-[11px] text-muted-foreground">
              {providerMeta ? t(providerMeta.hintEn, providerMeta.hintVi) : '\u00A0'}
            </p>
          </div>
          <div className="min-w-0 space-y-1.5">
            <div className="flex min-h-[22px] items-center">
              <Label htmlFor={`${id}-key`}>API key</Label>
            </div>
            <Input id={`${id}-key`} type="password" autoComplete="off" spellCheck={false} maxLength={4096}
              value={apiKey} onChange={(event) => { setApiKey(event.target.value); setSaved(false); setModels([]); setModelListOpen(false); }}
              placeholder={hasSavedKey ? t('Saved — leave blank to keep', 'Đã lưu — để trống để giữ key') : t('Enter provider API key', 'Nhập API key của provider')}
              aria-describedby={`${id}-key-help`} />
            <p id={`${id}-key-help`} className="min-h-[32px] line-clamp-2 text-[11px] text-muted-foreground">
              {hasSavedKey ? t('A key is saved for this provider.', 'Đã lưu key cho provider này.') : t('A key is required the first time you use each provider.', 'Cần nhập key khi sử dụng provider này lần đầu.')}
            </p>
          </div>
          <div className="min-w-0 space-y-1.5 sm:col-span-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <Label htmlFor={`${id}-model`}>Model</Label>
                {models.length > 0 && (
                  <span className="rounded-full bg-primary/10 px-2 py-0.5 font-mono text-[10px] font-medium text-primary">
                    {models.length} {t('available', 'khả dụng')}
                  </span>
                )}
              </div>
              <Button type="button" size="sm" variant="outline" disabled={!canUseKey || busy !== null} onClick={loadModels}>
                {busy === 'models' && <Loader2 className="h-3 w-3 animate-spin" />}
                {t('Load models', 'Tải danh sách model')}
              </Button>
            </div>
            <div className="relative">
              <Input id={`${id}-model`} list={`${id}-models`} value={model} maxLength={200} autoComplete="off"
                onFocus={() => {
                  if (models.length > 0) {
                    setFilterByInput(false);
                    setModelListOpen(true);
                  }
                }}
                onChange={(event) => {
                  setModel(event.target.value);
                  setFilterByInput(true);
                  if (models.length > 0) setModelListOpen(true);
                  setSaved(false);
                }}
                className="pr-14"
                placeholder={t('Choose or enter a model ID', 'Chọn hoặc nhập model ID')} aria-describedby={`${id}-model-help`} />
              <div className="absolute inset-y-0 right-1 flex items-center gap-0.5">
                {model && (
                  <button
                    type="button"
                    aria-label={t('Clear model name', 'Xóa tên model')}
                    onClick={() => {
                      setModel('');
                      setFilterByInput(false);
                      if (models.length > 0) setModelListOpen(true);
                      setSaved(false);
                    }}
                    className="rounded p-1 text-muted-foreground hover:bg-secondary hover:text-foreground"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
                {models.length > 0 && (
                  <button
                    type="button"
                    aria-label={t('Toggle model list', 'Mở hoặc đóng danh sách model')}
                    onClick={() => {
                      setFilterByInput(false);
                      setModelListOpen((prev) => !prev);
                    }}
                    className="rounded p-1 text-muted-foreground hover:bg-secondary hover:text-foreground"
                  >
                    <ChevronDown className={`h-3.5 w-3.5 transition-transform ${modelListOpen ? 'rotate-180' : ''}`} />
                  </button>
                )}
              </div>
                            {modelListOpen && models.length > 0 && (
                <div
                  role="listbox"
                  aria-label={t('Available models', 'Danh sách model khả dụng')}
                  className="absolute left-0 right-0 top-full z-20 mt-1.5 max-h-52 overflow-y-auto rounded-lg border border-border bg-popover p-1 shadow-lg"
                >
                  <div className="flex items-center justify-between border-b border-border/60 px-2.5 py-1 text-[10px] text-muted-foreground">
                    <span>
                      {t(
                        `Showing ${visibleModels.length} of ${models.length} models`,
                        `Hiển thị ${visibleModels.length} / ${models.length} model`,
                      )}
                    </span>
                    {filterByInput && model.trim() && visibleModels.length < models.length && (
                      <button
                        type="button"
                        onClick={() => setFilterByInput(false)}
                        className="font-medium text-primary hover:underline"
                      >
                        {t('Show all', 'Hiện tất cả')}
                      </button>
                    )}
                  </div>
                  {visibleModels.map((name) => {
                    const isSelected = name === model.trim();
                    return (
                      <button
                        key={name}
                        type="button"
                        role="option"
                        aria-selected={isSelected}
                        onClick={() => {
                          setModel(name);
                          setFilterByInput(false);
                          setModelListOpen(false);
                          setSaved(false);
                        }}
                        className={`flex w-full items-center justify-between gap-2 rounded-md px-2.5 py-1.5 text-left font-mono text-xs transition-colors ${
                          isSelected
                            ? 'bg-primary/10 font-semibold text-primary'
                            : 'text-foreground hover:bg-secondary/70'
                        }`}
                      >
                        <span className="truncate">{name}</span>
                        {isSelected && <Check className="h-3.5 w-3.5 shrink-0 text-primary" />}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
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

