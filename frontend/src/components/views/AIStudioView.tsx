'use client';

import { useEffect, useEffectEvent, useMemo, useRef, useState } from 'react';
import { MessageSquare, Sparkles } from 'lucide-react';
import { EditIcon } from '@/components/ui/EditIcon';

import {
  ChatMessageItem,
  ChatClarificationSelection,
  ChatSessionItem,
  createMetricApi,
  getChatSessionDetailApi,
  MetricPromptSuggestion,
  MetricSuggestion,
  MetricRequest,
  METRIC_WRITE_PERMISSION_MESSAGE,
  SemanticLayerData,
  isPermissionDenied,
  sendChatOrchestratorApi,
  listMetricRequestsApi,
  listMetricPromptSuggestionsApi,
  submitMetricRequestApi,
  reviewMetricProposalApi,
} from '@/lib/api';
import { ChatMessage, metricRequestKey, StudioChatStream } from '@/components/studio/StudioChatStream';
import { ViewHeader } from '@/components/workspace/ViewHeader';
import { Button } from '@/components/ui/button';
import { applySuggestedName, metricName } from '@/lib/metrics';
import { Translated } from '@/components/ui/translated';
import { useLanguage } from '@/context/LanguageContext';
import { PendingChat, pendingChatKey, readPendingChat, storePendingChat } from '@/lib/pendingChat';
import { ChatProgressOptions, ChatStreamError } from '@/lib/chatStream';

interface AIStudioViewProps {
  layer: SemanticLayerData;
  theme: 'light' | 'dark';
  sessions?: ChatSessionItem[];
  setSessions?: React.Dispatch<React.SetStateAction<ChatSessionItem[]>>;
  activeSessionId?: string | null;
  setActiveSessionId?: React.Dispatch<React.SetStateAction<string | null>>;
  loadingSessions?: boolean;
  onSelectSession?: (id: string) => void;
  onNewChat?: () => void;
  onMetricsChanged: () => Promise<void> | void;
  onEditMetricRequest?: (metric: MetricSuggestion) => void;
  onOpenCatalog?: () => void;
  onNotify?: (message: string) => void;
  mode?: 'data_assistant' | 'metric_studio';
  refreshKey?: number;
}

export function AIStudioView({
  layer,
  theme,
  sessions = [],
  setSessions,
  activeSessionId = null,
  setActiveSessionId,
  loadingSessions = false,
  onNewChat,
  onMetricsChanged,
  onEditMetricRequest,
  onOpenCatalog,
  onNotify,
  mode = 'metric_studio',
  refreshKey = 0,
}: AIStudioViewProps) {
  const { translate } = useLanguage();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [activePrompt, setActivePrompt] = useState('');
  const [metricRequests, setMetricRequests] = useState<MetricRequest[]>([]);
  const [promptSuggestions, setPromptSuggestions] = useState<{ dbId: string; items: MetricPromptSuggestion[] }>({
    dbId: '',
    items: [],
  });
  const semanticDbId = layer.semantic_db_id;
  const canGenerateMetrics = mode === 'metric_studio';
  const requestVersion = useRef(0);
  const requestController = useRef<AbortController | null>(null);
  const [reconnecting, setReconnecting] = useState(false);

  const submittedRequestKeys = useMemo(
    () =>
      new Set(
        metricRequests
          .filter((item) => item.status === 'pending')
          .map((item) => metricRequestKey(item.assistant_message_id, item.suggestion_index, item.proposal_id)),
      ),
    [metricRequests],
  );

  const approvedRequestKeys = useMemo(
    () =>
      new Set(
        metricRequests
          .filter((item) => item.status === 'approved')
          .map((item) => metricRequestKey(item.assistant_message_id, item.suggestion_index, item.proposal_id)),
      ),
    [metricRequests],
  );

  const activeSession = useMemo(
    () => sessions.find((s) => s.id === activeSessionId) || null,
    [sessions, activeSessionId],
  );

  const showWelcome = (error?: string) => {
    setMessages([
      {
        id: 'welcome',
        sender: 'assistant',
        text:
          error ||
          (canGenerateMetrics
            ? `Xin chào! Tôi đã quét schema cho database ${layer.db_name} (${layer.tables.length} bảng). Bạn có thể hỏi để tôi đề xuất và định nghĩa Business Metrics.`
            : `Xin chào! Tôi có thể giúp bạn tìm hiểu schema, metric đã phê duyệt và cách chọn dữ liệu trong ${layer.db_name}.`),
        timestamp: now(),
        isError: Boolean(error),
      },
    ]);
  };

  const send = async (
    prompt: string, _targetTables: string[], reuseMetricId?: number,
    selection?: ChatClarificationSelection, pending?: PendingChat,
    proposalMode: 'requested' | 'discovery' = pending?.proposalMode || 'requested',
  ) => {
    const clientMessageId = pending?.clientMessageId || crypto.randomUUID();
    const requestSessionId = pending ? pending.sessionId : activeSessionId;
    const version = requestVersion.current;

    setMessages((current) => [
      ...current.filter((item) => item.id !== clientMessageId),
      { id: clientMessageId, sender: 'user', text: prompt, timestamp: now() },
    ]);
    if (!semanticDbId) {
      return appendError(
        setMessages,
        'Semantic Layer đang được khởi tạo. Vui lòng tải lại sau khi enrichment hoàn tất.',
      );
    }
    const storageKey = pendingChatKey(semanticDbId, requestSessionId);
    storePendingChat(storageKey, { prompt, clientMessageId, sessionId: requestSessionId, reuseMetricId, selection, proposalMode });
    setLoading(true);
    setReconnecting(false);
    requestController.current?.abort();
    const controller = new AbortController();
    requestController.current = controller;
    const thinkingId = `${clientMessageId}:thinking`;
    const progress: ChatProgressOptions = {
      signal: controller.signal,
      onTrace: (trace) => {
        if (version !== requestVersion.current) return;
        setMessages((current) => [...current.filter((item) => item.id !== thinkingId), {
          id: thinkingId, sender: 'assistant', text: '', timestamp: now(), executionTrace: trace,
        }]);
      },
      onReconnecting: (value) => {
        if (version !== requestVersion.current) return;
        setReconnecting(value);
        setMessages((current) => current.map((item) => item.id === thinkingId ? { ...item, reconnecting: value } : item));
      },
    };
    try {
      const response = await sendChatOrchestratorApi(
        String(semanticDbId), prompt, requestSessionId, clientMessageId, selection || null, reuseMetricId ?? null, progress, proposalMode,
      );
      if (readPendingChat(storageKey)?.clientMessageId === clientMessageId) storePendingChat(storageKey, null);
      if (version !== requestVersion.current) return;
      if (response.session_id) {
        setActiveSessionId?.(response.session_id);
        if (typeof window !== 'undefined') {
          const url = new URL(window.location.href);
          url.searchParams.set('chat', response.session_id);
          window.history.replaceState({}, '', url);
        }
      }
      if (response.session) {
        setSessions?.((current) => [
          response.session!,
          ...current.filter((item) => item.id !== response.session!.id),
        ]);
      }
      if (response.intent === 'semantic_query') {
        setMessages((current) => [
          ...current.filter((item) => item.id !== thinkingId),
          {
            executionTrace: response.execution_trace,
            isError: response.execution_trace?.status === 'error',
            id: response.assistant_message_id || crypto.randomUUID(),
            sender: 'assistant',
            text: response.chat_response || '',
            queryResult: response.semantic_query_result,
            clarification: response.clarification,
            timestamp: now(),
          },
        ]);
        return;
      }
      if (response.intent === 'chitchat' || response.intent === 'data_question' || response.intent === 'out_of_scope') {
        setMessages((current) => [
          ...current.filter((item) => item.id !== thinkingId),
          {
            executionTrace: response.execution_trace,
            isError: response.execution_trace?.status === 'error',
            id: response.assistant_message_id || crypto.randomUUID(),
            sender: 'assistant',
            text: response.chat_response || 'Xin chào! Tôi có thể giúp gì cho bạn?',
            clarification: response.clarification,
            timestamp: now(),
          },
        ]);
        return;
      }
      const suggestions = response.suggestions || [];
      const duplicates = response.duplicates || [];
      setMessages((current) => [
        ...current.filter((item) => item.id !== thinkingId),
        {
          executionTrace: response.execution_trace,
          isError: response.execution_trace?.status === 'error',
          id: response.assistant_message_id || crypto.randomUUID(),
          sender: 'assistant',
          text:
            response.chat_response ||
            (suggestions.length
              ? `Dựa trên schema của bạn, tôi đề xuất ${suggestions.length} Metric Definition dưới đây. Bạn có thể xem trước YAML và lưu vào catalog để duyệt:`
              : duplicates.length > 0
                ? 'Hệ thống nhận thấy chỉ số này đã tồn tại trong Semantic Layer. Bạn có thể sử dụng trực tiếp chỉ số có sẵn bên dưới để tính toán kết quả.'
                : 'Tôi chưa tìm thấy cấu trúc dữ liệu phù hợp trong hệ thống để tự động đề xuất chỉ số này. Bạn có thể thử mô tả chi tiết hơn về các trường dữ liệu cần dùng nhé!'),
          suggestions,
          blockedCandidates: response.blocked_candidates,
          runStatus: response.run_status,
          clarification: response.clarification,
          duplicates: response.duplicates,
          dedupeSkipped: response.dedupe_performed === false,
          suggestionAction: response.suggestion_action,
          timestamp: now(),
        },
      ]);
    } catch (error) {
      if (version !== requestVersion.current || controller.signal.aborted) return;
      if (error instanceof ChatStreamError && error.trace) {
        const failedTrace = error.trace;
        if (failedTrace.status !== 'running' && readPendingChat(storageKey)?.clientMessageId === clientMessageId) storePendingChat(storageKey, null);
        setMessages((current) => [...current.filter((item) => item.id !== thinkingId), {
          id: thinkingId, sender: 'assistant', text: error.message, timestamp: now(), isError: true,
          executionTrace: failedTrace, reconnecting: failedTrace.status === 'running',
        }]);
      } else {
        setMessages((current) => current.filter((item) => item.id !== thinkingId));
        appendError(setMessages, error instanceof Error ? error.message : 'Không thể xử lý yêu cầu');
      }
    } finally {
      if (version === requestVersion.current) setLoading(false);
    }
  };

  const resumeRequest = useEffectEvent((request: PendingChat) => send(
    request.prompt, [], request.reuseMetricId, request.selection, request,
  ));

  useEffect(() => {
    const version = ++requestVersion.current;
    setLoading(false);
    if (!semanticDbId || layer.source_type !== 'live') {
      showWelcome();
      return;
    }

    if (!activeSessionId) {
      showWelcome();
      const pending = readPendingChat(pendingChatKey(semanticDbId, null));
      if (pending) void resumeRequest(pending);
      return () => { requestVersion.current = version + 1; requestController.current?.abort(); };
    }

    const loadDetail = async () => {
      try {
        const detail = await getChatSessionDetailApi(String(semanticDbId), activeSessionId);
        if (version !== requestVersion.current) return;
        const storageKey = pendingChatKey(semanticDbId, activeSessionId);
        let pending = readPendingChat(storageKey);
        if (pending && detail.messages.some((item) => item.client_message_id === `${pending!.clientMessageId}:assistant`)) {
          storePendingChat(storageKey, null);
          pending = null;
        }
        setMessages(detail.messages.filter((item) => item.sender !== 'system'
          && (!pending || item.client_message_id !== pending.clientMessageId)).map(toChatMessage));
        if (pending) void resumeRequest(pending);
      } catch (error) {
        if (version === requestVersion.current) {
          appendError(
            setMessages,
            error instanceof Error ? error.message : 'Không thể tải lịch sử cuộc trò chuyện.',
          );
        }
      }
    };

    void loadDetail();
    return () => { requestVersion.current = version + 1; requestController.current?.abort(); };
  }, [activeSessionId, layer.db_name, layer.source_type, semanticDbId]);

  useEffect(() => {
    if (!semanticDbId || canGenerateMetrics) return;
    void listMetricRequestsApi(String(semanticDbId)).then(setMetricRequests).catch(() => setMetricRequests([]));
  }, [canGenerateMetrics, semanticDbId, refreshKey]);

  useEffect(() => {
    const dbId = semanticDbId ? String(semanticDbId) : '';
    setPromptSuggestions({ dbId, items: [] });
    if (!dbId || !canGenerateMetrics) return;
    let active = true;
    void listMetricPromptSuggestionsApi(dbId)
      .then(({ items }) => { if (active) setPromptSuggestions({ dbId, items }); })
      .catch(() => { if (active) setPromptSuggestions({ dbId, items: [] }); });
    return () => { active = false; };
  }, [canGenerateMetrics, semanticDbId]);

  const handleSelectClarification = (assistantMessageId: string, optionId: string, label: string) =>
    send(label, [], undefined, { assistant_message_id: assistantMessageId, option_id: optionId });

  const updateMessage = (messageId: string, updater: (message: ChatMessage) => ChatMessage): void => {
    setMessages((current) => current.map((message) => (message.id === messageId ? updater(message) : message)));
  };

  const renameSuggestion = async (messageId: string, index: number): Promise<void> => {
    const current = messages.find(message => message.id === messageId)?.suggestions?.[index];
    if (!current?.proposal_id || !semanticDbId) return;
    try {
      const renamed = applySuggestedName(current);
      if (!canGenerateMetrics) {
        await send(`Tạo lại metric ${current.definition.metric.name} theo yêu cầu đã xác nhận, đặt tên: ${renamed.definition.metric.name}.`, []);
        return;
      }
      const result = await reviewMetricProposalApi(String(semanticDbId), current.proposal_id, renamed.definition);
      if (result.review.status !== 'pass' || !result.definition) throw new Error(result.review.summary);
      updateMessage(messageId, (message) => ({
        ...message,
        suggestions: message.suggestions?.map((item, itemIndex) =>
          itemIndex === index ? { ...renamed, ...result, definition: result.definition! } : item,
        ),
      }));
    } catch (error) {
      appendError(setMessages, error instanceof Error ? error.message : 'Không thể thẩm định tên mới.');
    }
  };

  const useExistingSuggestion = (messageId: string, index: number): void => {
    const conflict = messages.find((message) => message.id === messageId)?.suggestions?.[index]?.conflict;
    if (!conflict) return;
    if (conflict.existing_metric_status !== 'approved' || !conflict.existing_metric_id) {
      appendError(setMessages, `Chỉ số "${conflict.existing_metric_name}" chưa được phê duyệt hoặc không còn khả dụng. Vui lòng kiểm tra trong Catalog trước khi truy vấn.`);
      return;
    }
    void send(`Tính kết quả từ chỉ số "${conflict.existing_metric_name}"`, [], conflict.existing_metric_id);
  };

  const dismissDuplicate = (messageId: string, index: number): void =>
    updateMessage(messageId, (message) => ({
      ...message,
      duplicates: message.duplicates?.filter((_, itemIndex) => itemIndex !== index),
    }));

  const useExistingDuplicate = (messageId: string, index: number): void => {
    const targetMessage = messages.find((m) => m.id === messageId);
    const notice = targetMessage?.duplicates?.[index];
    const targetMetricName = notice?.existing_metric_name || '';
    const isApproved = notice?.existing_metric_status === 'approved' || !notice?.existing_metric_status;

    if (targetMetricName) {
      if (!isApproved || !notice?.existing_metric_id) {
        onNotify?.(
          `Chỉ số "${targetMetricName}" đang ở trạng thái chờ duyệt. Vui lòng phê duyệt trong Catalog trước khi truy vấn.`,
        );
        return;
      }
      updateMessage(messageId, (message) => {
        if (!message.duplicates?.[index]) return message;
        const duplicates = message.duplicates.map((item, itemIndex) =>
          itemIndex === index ? { ...item, resolved: true } : item,
        );
        return { ...message, duplicates };
      });
      void send(`Tính kết quả từ chỉ số "${targetMetricName}"`, [], notice.existing_metric_id);
    }
  };

  const save = async (suggestion: MetricSuggestion) => {
    if (!semanticDbId) {
      appendError(
        setMessages,
        'Semantic database chưa sẵn sàng hoặc đã bị xóa. Vui lòng tải lại trang.',
      );
      return;
    }
    try {
      await createMetricApi(String(semanticDbId), {
        definition: suggestion.definition,
        source: 'ai',
        proposal_id: suggestion.proposal_id,
      });
      await onMetricsChanged();
    } catch (error) {
      if (isPermissionDenied(error)) onNotify?.(METRIC_WRITE_PERMISSION_MESSAGE);
      appendError(
        setMessages,
        isPermissionDenied(error)
          ? METRIC_WRITE_PERMISSION_MESSAGE
          : `Không thể lưu chỉ số "${suggestion.definition.metric.name}": ${
              error instanceof Error ? error.message : 'Lỗi không xác định'
            }`,
      );
      throw error;
    }
  };

  const submitRequest = async (assistantMessageId: string, suggestionIndex: number) => {
    if (!semanticDbId) throw new Error('Semantic database chưa sẵn sàng.');
    try {
      const request = await submitMetricRequestApi(String(semanticDbId), assistantMessageId, suggestionIndex);
      setMetricRequests((current) => [request, ...current]);
      onNotify?.('Đã gửi yêu cầu cho Data Lead xem xét.');
    } catch (error) {
      // The server refuses duplicate submissions — surface it instead of failing silently.
      appendError(setMessages, error instanceof Error ? error.message : 'Không thể gửi yêu cầu.');
    }
  };

  const dbProp = {
    id: layer.id,
    name: layer.db_name,
    engine: layer.db_type === 'auto' ? ('dump' as const) : layer.db_type,
    status: 'connected' as const,
    tables: layer.tables.length,
  };

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      <ViewHeader
        eyebrow={canGenerateMetrics ? 'Generate' : 'Explore'}
        title={canGenerateMetrics ? 'Metric Studio' : 'Data Assistant'}
        description={
          canGenerateMetrics
            ? 'Chat with the assistant to explore your schema and generate business metric definitions.'
            : 'Hỏi về schema, metric đã duyệt và cách khai thác dữ liệu an toàn.'
        }
        database={dbProp}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" variant="outline" size="sm" className="gap-2"
              disabled={loading || loadingSessions}
              onClick={() => void send('Khám phá các KPI phù hợp với schema bán lẻ/ecommerce này.', [], undefined, undefined, undefined, 'discovery')}>
              <Sparkles className="h-4 w-4" />Đề xuất KPI
            </Button>
            {activeSession ? (
              <>
                <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-secondary px-3 py-1 font-sans text-xs text-secondary-foreground">
                  <MessageSquare className="h-3.5 w-3.5 text-primary" />
                  <span className="max-w-[200px] truncate">{activeSession.title}</span>
                </span>
                {onNewChat && (
                  <button
                    type="button"
                    onClick={onNewChat}
                    className="inline-flex items-center gap-1 rounded-md border border-border bg-card px-2.5 py-1 font-sans text-xs font-medium text-foreground transition-colors hover:bg-accent cursor-pointer"
                    title={translate("Tạo cuộc trò chuyện mới")}
                  >
                    <EditIcon size={12} />
                    <span><Translated text={"Đoạn chat mới"} /></span>
                  </button>
                )}
              </>
            ) : onNewChat && layer.source_type === 'live' && semanticDbId ? (
              <button
                type="button"
                onClick={onNewChat}
                className="inline-flex items-center gap-1 rounded-md border border-border bg-card px-2.5 py-1 font-sans text-xs font-medium text-foreground transition-colors hover:bg-accent cursor-pointer"
                title={translate("Tạo cuộc trò chuyện mới")}
              >
                <EditIcon size={12} />
                <span><Translated text={"Đoạn chat mới"} /></span>
              </button>
            ) : undefined}
          </div>
        }
      />
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        {!canGenerateMetrics && metricRequests.length > 0 && (
          <div className="border-b border-border px-6 py-2 text-xs text-muted-foreground">
            <Translated text={"Yêu cầu của bạn:"} after />{metricRequests.filter((item) => item.status === 'pending').length} <Translated text={"chờ xử lý ·"} after />{metricRequests.filter((item) => item.status === 'approved').length} <Translated text={"đã duyệt."} /></div>
        )}
        <StudioChatStream
          conversationKey={activeSessionId}
          reconnecting={reconnecting}
          messages={messages}
          onSendMessage={send}
          isLoading={loading || loadingSessions}
          tableNames={layer.tables.map((table) => table.table_name)}
          onAddMetric={canGenerateMetrics ? save : undefined}
          onEditMetric={canGenerateMetrics ? onEditMetricRequest : undefined}
          onRefineWithAI={
            canGenerateMetrics
              ? (suggestion) =>
                  setActivePrompt(`Hãy điều chỉnh chỉ số ${suggestion.definition.metric.name}: `)
              : undefined
          }
          activePromptText={activePrompt}
          theme={theme}
          mode={mode}
          metricPromptSuggestions={
            canGenerateMetrics && promptSuggestions.dbId === String(semanticDbId)
              ? promptSuggestions.items
              : []
          }
          onOpenCatalog={onOpenCatalog}
          onRenameSuggestion={renameSuggestion}
          onUseExistingSuggestion={useExistingSuggestion}
          onDismissDuplicate={dismissDuplicate}
          onUseExistingDuplicate={useExistingDuplicate}
          onSubmitMetricRequest={!canGenerateMetrics ? submitRequest : undefined}
          onSelectClarification={handleSelectClarification}
          submittedRequestKeys={submittedRequestKeys}
          approvedRequestKeys={approvedRequestKeys}
          savedMetricNames={layer.metrics.map((metric) => metricName(metric))}
        />
      </div>
    </div>
  );
}

function toChatMessage(message: ChatMessageItem): ChatMessage {
  return {
    id: message.id,
    sender: message.sender === 'user' ? 'user' : 'assistant',
    text: message.content,
    suggestions: message.metadata_json?.suggestions,
    blockedCandidates: message.metadata_json?.blocked_candidates,
    runStatus: message.metadata_json?.run_status,
    duplicates: message.metadata_json?.duplicates,
    dedupeSkipped: message.metadata_json?.dedupe_performed === false,
    suggestionAction: message.metadata_json?.suggestion_action,
    queryResult: message.metadata_json?.semantic_query_result,
    clarification: message.metadata_json?.clarification,
    executionTrace: message.metadata_json?.execution_trace,
    timestamp: new Date(message.created_at).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
    }),
    isError: message.metadata_json?.status === 'error',
  };
}

function appendError(
  setter: React.Dispatch<React.SetStateAction<ChatMessage[]>>,
  text: string,
): void {
  setter((current) => [
    ...current,
    { id: crypto.randomUUID(), sender: 'assistant', text, timestamp: now(), isError: true },
  ]);
}

function now(): string {
  return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}
