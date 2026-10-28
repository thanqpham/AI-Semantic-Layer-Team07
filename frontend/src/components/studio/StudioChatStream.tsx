'use client';

import {
  ArrowUp,
  Check,
  Code2,
  Copy,
  Edit3,
  Lightbulb,
  RefreshCw,
  Save,
  Sparkles,
  User,
} from 'lucide-react';
import React, { KeyboardEvent, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { Button } from '@/components/ui/button';
import { BotMessageSquareIcon } from '@/components/ui/BotMessageSquareIcon';
import { MetricSuggestion, MetricCandidateReport } from '@/lib/api';
import { MetricReviewPanel } from '@/components/metrics/MetricReviewPanel';
import { cn } from '@/lib/utils';
import { StatusPill } from '@/components/workspace/shared';
import {
  ChatDuplicateNotice,
  ConflictWarningStrip,
  DuplicateNoticeCard,
} from '@/components/studio/DedupeWarnings';
import { ChatSemanticQueryResult, ChatClarificationPayload } from '@/lib/api';
import { ChatQueryResultCard } from '@/components/studio/ChatQueryResultCard';
import { formatMetricFormula, getMetricUsedColumns } from '@/lib/metrics';
import { Translated } from '@/components/ui/translated';
import { useLanguage } from '@/context/LanguageContext';
import { ExecutionTrace } from '@/lib/chatTrace';
import { AgentThinking } from './AgentThinking';
import { AgentFlowPanel } from './AgentFlowPanel';

export interface ChatMessage {
  runStatus?: 'completed' | 'partial' | 'needs_clarification' | 'error' | null;
  executionTrace?: ExecutionTrace | null;
  reconnecting?: boolean;
  id: string;
  sender: 'user' | 'assistant';
  text: string;
  suggestions?: MetricSuggestion[];
  blockedCandidates?: MetricCandidateReport[];
  duplicates?: ChatDuplicateNotice[];
  dedupeSkipped?: boolean;
  suggestionAction?: 'save_metric' | 'submit_metric_request' | null;
  queryResult?: ChatSemanticQueryResult | null;
  clarification?: ChatClarificationPayload | null;
  timestamp: string;
  isError?: boolean;
}

/** Dedupe-related message actions, addressed by (messageId, suggestion index). */
type SuggestionIndexHandler = (messageId: string, index: number) => void;

interface StudioChatStreamProps {
  conversationKey?: string | null;
  reconnecting?: boolean;
  messages: ChatMessage[];
  onSendMessage: (promptText: string, targetTables: string[]) => Promise<void>;
  isLoading: boolean;
  tableNames: string[];
  onAddMetric?: (suggestion: MetricSuggestion) => Promise<void> | void;
  onEditMetric?: (suggestion: MetricSuggestion) => void;
  onRefineWithAI?: (suggestion: MetricSuggestion) => void;
  activePromptText?: string;
  theme?: 'light' | 'dark';
  onOpenCatalog?: () => void;
  mode?: 'data_assistant' | 'metric_studio';
  savedMetricNames?: string[];
  submittedRequestKeys?: ReadonlySet<string>;
  approvedRequestKeys?: ReadonlySet<string>;
  onRenameSuggestion?: SuggestionIndexHandler;
  onUseExistingSuggestion?: SuggestionIndexHandler;
  onDismissDuplicate?: SuggestionIndexHandler;
  onUseExistingDuplicate?: SuggestionIndexHandler;
  onSubmitMetricRequest?: (messageId: string, suggestionIndex: number) => Promise<void>;
  onSelectClarification?: (assistantMessageId: string, optionId: string, label: string) => void;
}

export function metricRequestKey(messageId: string, suggestionIndex: number, proposalId?: string | null): string {
  return proposalId ? `proposal:${proposalId}` : `${messageId}:${suggestionIndex}`;
}

interface PromptSuggestionItem {
  icon: string;
  title: string;
  prompt: string;
}

const DEFAULT_SUGGESTIONS: PromptSuggestionItem[] = [
  {
    icon: '💰',
    title: 'Tạo metric doanh thu thuần',
    prompt: 'Đề xuất metric doanh thu thuần: xác định bảng gốc, cột tiền, trạng thái giao dịch được tính và cách trừ giảm giá, hoàn tiền. Nêu rõ các giả định chưa xác nhận từ schema.',
  },
  {
    icon: '📦',
    title: 'Số đơn hoàn tất',
    prompt: 'Đề xuất metric số đơn hoàn tất: đếm mã đơn duy nhất, xác định trạng thái hợp lệ và mốc thời gian ghi nhận. Kiểm tra nguy cơ đếm trùng khi nối bảng chi tiết.',
  },
  {
    icon: '🎫',
    title: 'Giá trị đơn hàng trung bình (AOV)',
    prompt: 'Đề xuất metric AOV = doanh thu thuần / số đơn hoàn tất trong cùng kỳ. Làm rõ cách xử lý đơn hủy, hoàn tiền và mẫu số bằng 0.',
  },
  {
    icon: '👥',
    title: 'Khách hàng mua hàng',
    prompt: 'Đề xuất metric số khách hàng mua hàng: đếm mã khách hàng duy nhất có giao dịch hợp lệ trong kỳ. Nêu cách xử lý đơn khách vãng lai và giao dịch bị hủy.',
  },
  {
    icon: '🔁',
    title: 'Tỷ lệ khách hàng quay lại',
    prompt: 'Đề xuất metric tỷ lệ khách hàng quay lại: xác định khách hàng có ít nhất hai đơn hợp lệ, mẫu số là khách hàng mua hàng trong kỳ. Làm rõ thời điểm xét đơn trước kỳ và công thức phần trăm.',
  },
  {
    icon: '📈',
    title: 'Tăng trưởng doanh thu MoM',
    prompt: 'Đề xuất metric tăng trưởng doanh thu thuần theo tháng = (doanh thu tháng này - tháng trước) / doanh thu tháng trước. Nêu cách xử lý tháng trước bằng 0 và múi giờ của ngày giao dịch.',
  },
];

const DATA_ASSISTANT_SUGGESTIONS: PromptSuggestionItem[] = [
  {
    icon: '📊',
    title: 'Doanh thu theo khách hàng',
    prompt: 'Tổng doanh thu theo khách hàng năm 2024',
  },
  {
    icon: '📅',
    title: 'Doanh thu tháng này',
    prompt: 'Doanh thu tháng này theo chi nhánh',
  },
  {
    icon: '🔎',
    title: 'Tìm metric doanh thu đã duyệt',
    prompt: 'Có những metric doanh thu nào đã được phê duyệt? Giải thích ngắn gọn từng metric.',
  },
  {
    icon: '🧭',
    title: 'Tìm bảng khách hàng',
    prompt: 'Bảng hoặc cột nào liên quan đến khách hàng trong semantic layer này?',
  },
];

export function StudioChatStream(props: StudioChatStreamProps) {
  const { translate } = useLanguage();
  const mode = props.mode || 'metric_studio';
  const canGenerateMetrics = mode === 'metric_studio';
  const [graph, setGraph] = useState<{ runId: string; title: string; trigger: HTMLButtonElement } | null>(null);
  const [conversationKey, setConversationKey] = useState(props.conversationKey);
  if (conversationKey !== props.conversationKey) {
    setConversationKey(props.conversationKey);
    if (conversationKey) setGraph(null);
  }
  const closeGraph = useCallback(() => setGraph(null), []);
  const graphMessage = props.messages.find((message) => message.executionTrace?.run_id === graph?.runId);
  const graphTrace = graphMessage?.executionTrace;
  const [input, setInput] = useState(props.activePromptText || '');
  const [savedProposalIds, setSavedProposalIds] = useState<string[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(true);
  const messagesRef = useRef<HTMLDivElement>(null);
  const stripRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ startX: number; scrollLeft: number; isDragging: boolean; moved: boolean }>({
    startX: 0,
    scrollLeft: 0,
    isDragging: false,
    moved: false,
  });

  const handlePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    const el = stripRef.current;
    if (!el) return;
    dragRef.current = {
      startX: e.clientX,
      scrollLeft: el.scrollLeft,
      isDragging: true,
      moved: false,
    };
  };

  const handlePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragRef.current.isDragging || !stripRef.current) return;
    const dx = e.clientX - dragRef.current.startX;
    if (Math.abs(dx) > 8) {
      dragRef.current.moved = true;
    }
    stripRef.current.scrollLeft = dragRef.current.scrollLeft - dx;
  };

  const handlePointerUp = () => {
    dragRef.current.isDragging = false;
    window.setTimeout(() => { dragRef.current.moved = false; }, 0);
  };

  const catalogNames = useMemo(() => {
    const set = new Set<string>();
    (props.savedMetricNames || []).forEach((name) => {
      if (name) set.add(name.trim().toLowerCase());
    });
    return set;
  }, [props.savedMetricNames]);

  useEffect(() => {
    if (props.activePromptText) {
      setInput(props.activePromptText);
    }
  }, [props.activePromptText]);

  useLayoutEffect(() => {
    const pane = messagesRef.current;
    if (pane) pane.scrollTop = pane.scrollHeight;
  }, [props.messages, props.isLoading]);

  const send = async () => {
    if (!input.trim() || props.isLoading) return;
    const text = input.trim();
    setInput('');
    await props.onSendMessage(text, props.tableNames);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  };

  const save = async (suggestion: MetricSuggestion, messageId: string, index: number) => {
    if (props.onAddMetric) {
      await props.onAddMetric(suggestion);
      const key = suggestion.proposal_id ? `proposal:${suggestion.proposal_id}` : `message:${messageId}:${index}`;
      setSavedProposalIds((prev) => [...new Set([...prev, key])]);
    }
  };

  const handleSelectSuggestion = (promptText: string) => {
    setInput(promptText);
  };

  const toggleShowSuggestions = () => {
    setShowSuggestions((prev) => !prev);
  };

  const contextualSuggestions = useMemo(() => {
    const list = [
      ...(canGenerateMetrics ? DEFAULT_SUGGESTIONS : DATA_ASSISTANT_SUGGESTIONS),
    ];
    const tableStr = props.tableNames.join(' ').toLowerCase();
    if (canGenerateMetrics && (tableStr.includes('order') || tableStr.includes('don_hang'))) {
      list.unshift({
        icon: '📈',
        title: 'Tỷ lệ hủy đơn hàng',
        prompt: 'Đề xuất metric tỷ lệ hủy đơn = số đơn hủy / tổng số đơn được tạo trong cùng kỳ. Đếm mã đơn duy nhất, xác định trạng thái hủy và ngày tạo đơn.',
      });
    }
    if (canGenerateMetrics && (tableStr.includes('product') || tableStr.includes('san_pham'))) {
      list.push({
        icon: '🏷️',
        title: 'Số lượng sản phẩm bán',
        prompt: 'Đề xuất metric số lượng sản phẩm bán từ chi tiết đơn hợp lệ: cộng số lượng sau hoàn trả, nêu đơn vị tính và cách nối sản phẩm mà không nhân bản dòng.',
      });
    }
    return list;
  }, [canGenerateMetrics, props.tableNames]);

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-1 overflow-hidden">
    <div className="flex h-full min-w-0 flex-1 flex-col overflow-hidden bg-background text-foreground">
      {/* 💬 Messages Stream */}
      <div ref={messagesRef} className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
        <div className="mx-auto flex max-w-4xl flex-col gap-3 px-4 py-3 sm:px-6">
          {!canGenerateMetrics && (
            <div role="status" className="rounded-lg border border-blue-500/30 bg-blue-500/10 px-4 py-3 text-xs text-blue-700 dark:text-blue-300">
              <Translated text={"Bạn không có quyền tạo, sửa hoặc lưu metric trực tiếp. Bạn có thể tra cứu dữ liệu qua các metric đã duyệt (chỉ áp dụng cho kết nối Live DB) hoặc yêu cầu AI tạo Business Metric mới. Metric sau khi tạo sẽ được lưu vào Semantic Layer ở trạng thái chờ Data Lead phê duyệt."} />
            </div>
          )}
          {props.messages.map((message, index) => (
            <MessageBubble
              key={message.executionTrace?.run_id || message.id}
              message={message}
              onOpenGraph={(trigger) => message.executionTrace && setGraph({
                runId: message.executionTrace.run_id, trigger,
                title: props.messages.slice(0, index).reverse().find((item) => item.sender === 'user')?.text || message.timestamp,
              })}
              catalogNames={catalogNames}
              savedProposalIds={new Set(savedProposalIds)}
              onSave={save}
              onEdit={props.onEditMetric}
              onRefine={props.onRefineWithAI}
              onOpenCatalog={props.onOpenCatalog}
              onSubmitMetricRequest={props.onSubmitMetricRequest}
              submittedKeys={props.submittedRequestKeys || new Set()}
              approvedKeys={props.approvedRequestKeys || new Set()}
              onRenameSuggestion={props.onRenameSuggestion}
              onUseExistingSuggestion={props.onUseExistingSuggestion}
              onDismissDuplicate={props.onDismissDuplicate}
              onUseExistingDuplicate={props.onUseExistingDuplicate}
              onSelectClarification={props.onSelectClarification}
              theme={props.theme}
            />
          ))}

          {props.isLoading && !props.messages.some((message) => message.executionTrace?.status === 'running') && (
            <div className="flex gap-4">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-border bg-primary text-primary-foreground">
                <BotMessageSquareIcon className="h-4 w-4" />
              </div>
              <div className="flex flex-col gap-2 rounded-lg border border-border bg-card px-4 py-3.5 shadow-xs">
                <div className="flex items-center gap-2 text-xs font-semibold text-foreground">
                  <Sparkles className="h-3.5 w-3.5 animate-spin text-primary" />
                  <span>
                    <Translated text={props.reconnecting ? 'Đang kết nối lại' : canGenerateMetrics
                      ? 'AI đang phân tích cấu trúc Schema & quan hệ...'
                      : 'AI đang đọc semantic layer và metric đã phê duyệt...'} />
                  </span>
                </div>
                <div className="flex items-center gap-1.5 pt-1">
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:-0.3s]" />
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:-0.15s]" />
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground" />
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* 💡 Suggested Prompts Bar */}
      <div className="shrink-0 px-4 pb-1 sm:px-6">
        <div className="mx-auto max-w-4xl">
          <div className="space-y-1 rounded-lg border border-border bg-card px-2.5 py-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Lightbulb className="h-3.5 w-3.5 text-amber-500" />
                <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                  <Translated text={canGenerateMetrics ? 'GỢI Ý CÂU HỎI TẠO METRIC' : 'GỢI Ý CÂU HỎI VỀ DỮ LIỆU'} />
                </span>
                {showSuggestions && (
                  <span className="font-mono text-[10px] text-muted-foreground/70">
                    ({contextualSuggestions.length} <Translated text={"mẫu)"} /></span>
                )}
              </div>

              <label className="inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={showSuggestions}
                  onChange={toggleShowSuggestions}
                  className="h-3.5 w-3.5 rounded border-border accent-primary cursor-pointer"
                />
                <span><Translated text={showSuggestions ? 'Hiển thị gợi ý' : 'Đã ẩn (Tick để hiện)'} /></span>
              </label>
            </div>

            {showSuggestions && (
              <div
                ref={stripRef}
                data-testid="prompt-suggestion-strip"
                onPointerDown={handlePointerDown}
                onPointerMove={handlePointerMove}
                onPointerUp={handlePointerUp}
                onPointerCancel={handlePointerUp}
                onClickCapture={(e) => {
                  if (dragRef.current.moved) e.stopPropagation();
                }}
                className="flex gap-1.5 overflow-x-auto whitespace-nowrap touch-pan-x cursor-grab active:cursor-grabbing"
              >
                {contextualSuggestions.map((item, idx) => (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => handleSelectSuggestion(translate(item.prompt))}
                    className="inline-flex shrink-0 items-center gap-1 rounded-full border border-border bg-secondary/60 px-2.5 py-0.5 text-xs text-muted-foreground transition-colors hover:border-foreground/30 hover:bg-secondary hover:text-foreground cursor-pointer"
                  >
                    <span>{item.icon}</span>
                    <span><Translated text={item.title} /></span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Composer Input Box */}
      <div className="shrink-0 bg-card/40 px-4 py-2 sm:px-6">
        <div className="mx-auto max-w-4xl space-y-1.5">
          <div className="flex items-end gap-2 rounded-xl border border-border bg-card p-1.5 shadow-xs focus-within:border-foreground/30 focus-within:ring-1 focus-within:ring-ring/20">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={1}
              placeholder={translate(
                canGenerateMetrics
                  ? 'Mô tả chỉ số bạn muốn tạo hoặc đặt câu hỏi về schema...'
                  : 'Hỏi về schema, metric đã duyệt hoặc cách chọn dữ liệu...'
              )}
              className="max-h-40 min-h-8 flex-1 resize-none bg-transparent px-2 py-1.5 text-sm text-foreground outline-none placeholder:text-muted-foreground"
            />
            <Button
              size="icon"
              className="h-8 w-8 shrink-0 rounded-lg cursor-pointer"
              onClick={() => void send()}
              disabled={!input.trim() || props.isLoading}
              aria-label={translate("Send message")}
            >
              <ArrowUp className="h-4 w-4" />
            </Button>
          </div>
          <p className="text-center font-mono text-[10px] text-muted-foreground">
            <Translated text={canGenerateMetrics
              ? 'AI can make mistakes. Every generated metric requires human approval before use.'
              : 'AI chỉ trả lời dựa trên semantic layer và metric đã được cấp quyền.'} />
          </p>
        </div>
      </div>
    </div>
    {graph && graphTrace && <AgentFlowPanel key={graph.runId} trace={graphTrace} reconnecting={graphMessage?.reconnecting} title={graph.title} onClose={closeGraph} trigger={graph.trigger} />}
    </div>
  );
}

function MessageBubble({
  onOpenGraph,
  message,
  catalogNames,
  savedProposalIds,
  onSave,
  onEdit,
  onRefine,
  onOpenCatalog,
  onSubmitMetricRequest,
  submittedKeys,
  approvedKeys,
  onRenameSuggestion,
  onUseExistingSuggestion,
  onDismissDuplicate,
  onUseExistingDuplicate,
  onSelectClarification,
  theme,
}: {
  onOpenGraph?: (trigger: HTMLButtonElement) => void;
  message: ChatMessage;
  catalogNames: ReadonlySet<string>;
  savedProposalIds: ReadonlySet<string>;
  onSave: (suggestion: MetricSuggestion, messageId: string, index: number) => Promise<void>;
  onEdit?: (suggestion: MetricSuggestion) => void;
  onRefine?: (suggestion: MetricSuggestion) => void;
  onOpenCatalog?: () => void;
  onSubmitMetricRequest?: (messageId: string, suggestionIndex: number) => Promise<void>;
  submittedKeys: ReadonlySet<string>;
  approvedKeys: ReadonlySet<string>;
  onRenameSuggestion?: SuggestionIndexHandler;
  onUseExistingSuggestion?: SuggestionIndexHandler;
  onDismissDuplicate?: SuggestionIndexHandler;
  onUseExistingDuplicate?: SuggestionIndexHandler;
  onSelectClarification?: (assistantMessageId: string, optionId: string, label: string) => void;
  theme?: 'light' | 'dark';
}) {
  const isUser = message.sender === 'user';
  const candidateGroups = groupMetricCandidates(message.suggestions || [], message.blockedCandidates || []);

  return (
    <div className={cn('flex gap-2.5', isUser && 'flex-row-reverse')}>
      <div
        className={cn(
          'flex h-6 w-6 shrink-0 items-center justify-center rounded-md border',
          isUser
            ? 'border-border bg-secondary text-secondary-foreground'
            : 'border-border bg-primary text-primary-foreground',
        )}
      >
        {isUser ? <User className="h-3 w-3" /> : <BotMessageSquareIcon className="h-3 w-3" />}
      </div>

      <div className={cn('min-w-0 flex-1 space-y-1.5', isUser && 'flex flex-col items-end')}>
        <div className="flex items-center gap-1.5 font-mono text-[10px] text-muted-foreground">
          <span className="font-semibold text-foreground">
            <Translated text={isUser ? 'Bạn' : 'AI Semantic Agent'} />
          </span>
          <span>·</span>
          <span>{message.timestamp}</span>
        </div>

        {!isUser && message.executionTrace && <AgentThinking trace={message.executionTrace}
          reconnecting={message.reconnecting} onOpenGraph={(trigger) => onOpenGraph?.(trigger)} />}
        {/* The description line is hidden once every duplicate notice is settled. */}
        {message.text && !message.suggestions?.length ? (
          <div
            className={cn(
              'inline-block break-words rounded-xl px-2.5 py-1.5 text-[13px] leading-5 shadow-2xs',
              isUser
                ? 'max-w-[80%] bg-secondary text-secondary-foreground'
                : 'max-w-2xl border border-border bg-card text-card-foreground',
              message.isError && 'border-destructive/30 bg-destructive/10 text-destructive',
            )}
          >
            {isUser ? message.text : <AssistantMarkdown content={message.text} />}
          </div>
        ) : null}

        {/* 📊 Semantic Query Result Snapshot */}
        {message.queryResult && (
          <div className="w-full pt-1">
            <ChatQueryResultCard result={message.queryResult} theme={theme} />
          </div>
        )}

        {/* ❓ Clarification Options */}
        {message.clarification?.options && message.clarification.options.length > 0 && (
          <div className="w-full space-y-2 pt-1">
            <div className="flex flex-wrap gap-2">
              {message.clarification.options.map((opt) => (
                <button
                  key={opt.id}
                  type="button"
                  onClick={() => onSelectClarification?.(message.id, opt.id, opt.label)}
                  className="flex flex-col items-start gap-0.5 rounded-lg border border-primary/30 bg-primary/10 px-3 py-2 text-left text-xs font-medium text-primary hover:bg-primary/20 hover:border-primary/50 transition-all cursor-pointer shadow-2xs"
                >
                  <span>{opt.label}</span>
                  {opt.description && <span className="text-[10px] font-normal text-muted-foreground">{opt.description}</span>}
                </button>
              ))}
            </div>
          </div>
        )}

        {message.dedupeSkipped && (
          <div
            role="status"
            className="w-full rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 font-mono text-[11px] text-amber-700 dark:text-amber-300"
          >
            <Translated text={"⚠️ Không kiểm tra được trùng lặp (dedupe unavailable) — danh sách chưa so với metric đã lưu."} />
          </div>
        )}

        {message.runStatus === 'partial' && <p role="status" className="rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-xs">
          Một phần tác vụ đã hoàn tất. Các KPI đạt vẫn có thể gửi duyệt; phần lỗi được ghi riêng bên dưới.
        </p>}
        {candidateGroups.length > 0 && (
          <div className="w-full overflow-hidden rounded-xl border border-border bg-card shadow-xs">
            <div className="border-b border-border bg-secondary/20 px-4 py-3 text-sm leading-relaxed text-card-foreground">
              <AssistantMarkdown content={message.text || `Đề xuất ${message.suggestions?.length || 0} Metric Definition`} />
            </div>
            {candidateGroups.map((group) => (
              <section key={group.id}>
                {group.name && <h3 className="border-b border-border bg-secondary/10 px-4 py-2 text-xs font-semibold">{group.name}</h3>}
                {group.items.map((entry) => entry.kind === 'blocked' ? (
                  <div key={entry.item.proposal_id || entry.item.candidate_id || `blocked-${entry.index}`} className="border-b border-border p-4 last:border-b-0">
                    <p className="text-sm font-medium">{entry.item.name}</p>
                    <MetricReviewPanel review={entry.item.review} />
                  </div>
                ) : (
                  <SuggestionCard
                    key={entry.item.proposal_id || entry.item.candidate_id || `suggestion-${entry.index}`}
                    suggestion={entry.item}
                    embedded
                    isSaved={savedProposalIds.has(suggestionStateKey(entry.item, message.id, entry.index))}
                    catalogNameConflict={catalogNames.has(entry.item.definition.metric.name.trim().toLowerCase())}
                    onSave={() => onSave(entry.item, message.id, entry.index)}
                    onEdit={() => onEdit?.(entry.item)}
                    onRefine={() => onRefine?.(entry.item)}
                    onOpenCatalog={onOpenCatalog}
                    action={message.suggestionAction}
                    isSubmitted={submittedKeys.has(metricRequestKey(message.id, entry.index, entry.item.proposal_id))}
                    isApproved={approvedKeys.has(metricRequestKey(message.id, entry.index, entry.item.proposal_id)) || savedProposalIds.has(suggestionStateKey(entry.item, message.id, entry.index))}
                    onSubmitRequest={onSubmitMetricRequest ? () => onSubmitMetricRequest(message.id, entry.index) : undefined}
                    onRename={() => onRenameSuggestion?.(message.id, entry.index)}
                    onUseExisting={() => onUseExistingSuggestion?.(message.id, entry.index)}
                  />
                ))}
              </section>
            ))}
          </div>
        )}

        {message.duplicates && message.duplicates.length > 0 && (
          <div className="w-full space-y-3 pt-1">
            {message.duplicates.map((notice, idx) => (
              <DuplicateNoticeCard
                key={`${message.id}-dup-${idx}`}
                notice={notice}
                onDismiss={() => onDismissDuplicate?.(message.id, idx)}
                onUseExisting={() => onUseExistingDuplicate?.(message.id, idx)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

type CandidateEntry =
  | { kind: 'suggestion'; item: MetricSuggestion; index: number }
  | { kind: 'blocked'; item: MetricCandidateReport; index: number };

interface CandidateGroup {
  id: string;
  name?: string;
  items: CandidateEntry[];
}

function suggestionStateKey(suggestion: MetricSuggestion, messageId: string, index: number): string {
  return suggestion.proposal_id ? `proposal:${suggestion.proposal_id}` : `message:${messageId}:${index}`;
}

function groupMetricCandidates(suggestions: MetricSuggestion[], blocked: MetricCandidateReport[]): CandidateGroup[] {
  const groups = new Map<string, CandidateGroup>();
  const add = (id: string, name: string | undefined, entry: CandidateEntry) => {
    const group = groups.get(id) || { id, name, items: [] };
    if (!group.name && name) group.name = name;
    group.items.push(entry);
    groups.set(id, group);
  };
  suggestions.forEach((suggestion, index) => {
    const id = suggestion.group_id || `candidate-${index}`;
    add(id, suggestion.group_name || undefined, { kind: 'suggestion', item: suggestion, index });
  });
  blocked.forEach((candidate, index) => {
    const id = candidate.group_id || `blocked-${index}`;
    add(id, candidate.group_name || undefined, { kind: 'blocked', item: candidate, index });
  });
  return [...groups.values()];
}

function renderFormattedContent(node: React.ReactNode): React.ReactNode {
  if (typeof node === 'string') {
    if (!/<br\s*\/?>/i.test(node)) {
      return node;
    }
    const parts = node.split(/(<br\s*\/?>)/gi);
    return parts.map((part, i) => {
      if (/<br\s*\/?>/i.test(part)) {
        return <br key={i} className="my-0.5" />;
      }
      return part;
    });
  }
  if (Array.isArray(node)) {
    return React.Children.map(node, renderFormattedContent);
  }
  if (React.isValidElement(node) && (node.props as { children?: React.ReactNode })?.children) {
    return React.cloneElement(
      node,
      undefined,
      renderFormattedContent((node.props as { children?: React.ReactNode }).children),
    );
  }
  return node;
}

function AssistantMarkdown({ content }: { content: string }) {
  return (
    <div className="prose prose-sm max-w-none text-[13px] text-card-foreground prose-headings:font-display prose-headings:text-foreground prose-p:my-1 prose-p:leading-5 prose-strong:text-foreground prose-li:my-1 prose-li:leading-5 prose-a:text-primary prose-a:underline prose-blockquote:border-primary/40 prose-blockquote:text-muted-foreground">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => <h3 className="mb-2 mt-4 text-base font-semibold first:mt-0">{renderFormattedContent(children)}</h3>,
          h2: ({ children }) => <h3 className="mb-2 mt-4 text-base font-semibold first:mt-0">{renderFormattedContent(children)}</h3>,
          h3: ({ children }) => <h4 className="mb-2 mt-3 text-sm font-semibold">{renderFormattedContent(children)}</h4>,
          p: ({ children }) => <p className="my-1 leading-5 first:mt-0 last:mb-0">{renderFormattedContent(children)}</p>,
          strong: ({ children }) => <strong className="font-semibold text-foreground">{renderFormattedContent(children)}</strong>,
          em: ({ children }) => <em className="text-muted-foreground">{renderFormattedContent(children)}</em>,
          ul: ({ children }) => <ul className="my-2 list-disc space-y-1 pl-5">{renderFormattedContent(children)}</ul>,
          ol: ({ children }) => <ol className="my-2 list-decimal space-y-1 pl-5">{renderFormattedContent(children)}</ol>,
          li: ({ children }) => <li className="my-1">{renderFormattedContent(children)}</li>,
          blockquote: ({ children }) => (
            <blockquote className="my-3 border-l-2 pl-3 italic">{renderFormattedContent(children)}</blockquote>
          ),
          code: ({ className, children, ...props }) => (
            <code
              className={cn(
                className
                  ? 'block overflow-x-auto rounded-md bg-secondary/80 p-3 font-mono text-xs leading-5'
                  : 'rounded bg-secondary px-1.5 py-0.5 font-mono text-[0.85em] text-primary',
              )}
              {...props}
            >
              {children}
            </code>
          ),
          pre: ({ children }) => <pre className="my-3 overflow-x-auto rounded-md">{children}</pre>,
          table: ({ children }) => (
            <div className="my-3 overflow-x-auto rounded-lg border border-border bg-card shadow-xs">
              <table className="w-full min-w-[520px] border-collapse text-left text-xs">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-secondary/70 font-semibold">{children}</thead>,
          tbody: ({ children }) => <tbody className="divide-y divide-border [&>tr:last-child>td]:border-b-0">{children}</tbody>,
          tr: ({ children }) => <tr className="transition-colors hover:bg-muted/20">{children}</tr>,
          th: ({ children }) => <th className="border-b border-border px-3.5 py-2.5 font-semibold text-foreground">{children}</th>,
          td: ({ children }) => (
            <td className="border-b border-border px-3.5 py-2.5 align-top text-card-foreground leading-relaxed">
              {renderFormattedContent(children)}
            </td>
          ),
          hr: () => <hr className="my-4 border-border" />,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

function SuggestionCard({
  suggestion,
  embedded = false,
  isSaved,
  catalogNameConflict,
  onSave,
  onEdit,
  onRefine,
  onOpenCatalog,
  onRename,
  onUseExisting,
  action,
  isSubmitted,
  isApproved,
  onSubmitRequest,
}: {
  suggestion: MetricSuggestion;
  embedded?: boolean;
  isSaved: boolean;
  catalogNameConflict: boolean;
  onSave: () => Promise<void>;
  onEdit?: () => void;
  onRefine?: () => void;
  onOpenCatalog?: () => void;
  onRename?: () => void;
  onUseExisting?: () => void;
  action?: 'save_metric' | 'submit_metric_request' | null;
  isSubmitted?: boolean;
  isApproved?: boolean;
  onSubmitRequest?: () => Promise<void>;
}) {
  const [showYaml, setShowYaml] = useState(false);
  const [copied, setCopied] = useState(false);
  const [saving, setSaving] = useState(false);

  const def = suggestion.definition.metric;
  const yamlContent = suggestion.yaml_preview || JSON.stringify(suggestion.definition, null, 2);
  const usedColumns = getMetricUsedColumns(suggestion.definition);
  const ratio = def.formula.ratio;
  const filters = [
    ...(def.filters || []).map((filter) => ({ ...filter, scope: '' })),
    ...(ratio?.numerator.filters || []).map((filter) => ({ ...filter, scope: 'Tử số' })),
    ...(ratio?.denominator.filters || []).map((filter) => ({ ...filter, scope: 'Mẫu số' })),
  ];

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave();
    } catch {
      // Handled by parent error notification
    } finally {
      setSaving(false);
    }
  };

  const handleSubmitRequest = async () => {
    setSaving(true);
    try {
      await onSubmitRequest?.();
    } catch {
      // Handled by parent error notification
    } finally {
      setSaving(false);
    }
  };

  const copyYaml = () => {
    void navigator.clipboard?.writeText(yamlContent);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className={cn('w-full overflow-hidden', !embedded && 'rounded-lg border border-border bg-card shadow-xs')}>
      {/* ⚠️ Conflict clarify strip — same name as a saved metric, different formula */}
      {suggestion.conflict && (
        <div className="border-b border-border bg-secondary/20 p-3">
          <ConflictWarningStrip
            conflict={suggestion.conflict}
            onRename={() => onRename?.()}
            onUseExisting={() => onUseExisting?.()}
          />
        </div>
      )}
      {catalogNameConflict && !suggestion.conflict && (
        <div role="status" className="border-b border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
          Tên này đã có trong catalog. Kiểm tra metric hiện tại trước khi lưu biến thể.
        </div>
      )}

      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-secondary/30 px-4 py-2.5">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="font-semibold text-foreground text-sm">{def.name}</h3>
            <StatusPill status={def.status || 'pending_approval'} />
            <span className="rounded bg-secondary px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
              <Translated text={"Độ tin cậy:"} after /><Translated text={def.confidence === 'high' ? 'Cao' : def.confidence === 'medium' ? 'Trung bình' : 'Thấp'} />
            </span>
          </div>
        </div>

        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            className="h-7 gap-1.5 text-xs text-muted-foreground hover:text-foreground cursor-pointer"
            onClick={() => setShowYaml(!showYaml)}
          >
            <Code2 className="h-3.5 w-3.5" />
            <Translated text={showYaml ? 'Ẩn mã YAML' : 'Hiển thị mã YAML'} />
          </Button>
          {onRefine && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 gap-1.5 text-xs text-muted-foreground hover:text-foreground cursor-pointer"
              onClick={onRefine}
            >
              <RefreshCw className="h-3.5 w-3.5" />
              <Translated text={"Nhờ AI tinh chỉnh"} />
            </Button>
          )}
          {onEdit && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 gap-1.5 text-xs text-muted-foreground hover:text-foreground cursor-pointer"
              onClick={onEdit}
            >
              <Edit3 className="h-3.5 w-3.5" />
              <Translated text={"Chỉnh sửa thủ công"} />
            </Button>
          )}
        </div>
      </div>

      {/* Visual Properties */}
      <div className="space-y-2 p-4 text-xs">
        {suggestion.review && <MetricReviewPanel review={suggestion.review} definition={suggestion.definition} />}
        <div data-testid="metric-properties-grid" className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <div className="min-w-0 rounded-md border border-border bg-secondary/30 p-2.5">
            <span className="font-mono text-[10px] uppercase text-muted-foreground">
              <Translated text={"Công thức tính"} />
            </span>
            <p className="mt-0.5 break-words font-mono text-xs font-medium text-foreground">
              <span className="text-primary font-bold">{def.formula.function}</span>(
              <span>{def.formula.expression}</span>)
            </p>
          </div>
          <div className="min-w-0 rounded-md border border-border bg-secondary/30 p-2.5">
            <span className="font-mono text-[10px] uppercase text-muted-foreground">
              <Translated text={"Dựa vào bảng gốc"} />
            </span>
            <p className="mt-1 break-words font-mono text-xs font-medium text-foreground">
              {def.base_entity}
            </p>
          </div>
          <div className="min-w-0 rounded-md border border-border bg-secondary/30 p-2.5">
            <span className="font-mono text-[10px] uppercase text-muted-foreground">
              <Translated text={"Cột dữ liệu sử dụng"} />
            </span>
            <div className="mt-1 flex flex-wrap gap-1">
              {usedColumns.length ? usedColumns.map((column) => (
                <code key={column} className="rounded bg-secondary px-1.5 py-0.5 font-mono text-[11px] text-foreground">
                  {column}
                </code>
              )) : <span className="text-muted-foreground">Không có cột dữ liệu</span>}
            </div>
          </div>
          <div className="min-w-0 rounded-md border border-border bg-secondary/30 p-2.5">
            <span className="font-mono text-[10px] uppercase text-muted-foreground">
              <Translated text={"Bộ lọc điều kiện"} />
            </span>
            <p className="mt-1 break-words text-xs text-muted-foreground">
              {filters.length
                ? filters.map((filter) => {
                  const scope = filter.scope ? `${filter.scope}: ` : '';
                  const value = Array.isArray(filter.value)
                    ? filter.value.join(', ')
                    : String(filter.value ?? '');
                  return `${scope}${filter.field} ${filter.operator}${value ? ` ${value}` : ''}`;
                }).join(' · ')
                : 'Không có bộ lọc'}
            </p>
          </div>
        </div>
      </div>

      {(def.excluded_notes || showYaml) && (
        <div className="space-y-2 px-4 pb-4 text-xs">
          {def.excluded_notes && (
            <div className="rounded-md border border-amber-500/30 bg-amber-500/10 p-2.5">
              <span className="font-mono text-[10px] uppercase text-amber-700 dark:text-amber-300 font-semibold">
                <Translated text={"Giả định cần xác nhận"} />
              </span>
              <p className="mt-0.5 text-xs text-amber-800 dark:text-amber-200">
                {def.excluded_notes}
              </p>
            </div>
          )}

          {showYaml && (
            <div className="overflow-hidden rounded-md border border-border bg-secondary/20">
              <div className="flex items-center justify-between border-b border-border px-3 py-1.5">
                <span className="font-mono text-[11px] text-muted-foreground"><Translated text={"YAML preview"} /></span>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 gap-1 text-[11px] cursor-pointer"
                  onClick={copyYaml}
                >
                  {copied ? <Check className="h-3 w-3 text-emerald-500" /> : <Copy className="h-3 w-3" />}
                  <Translated text={copied ? 'Đã copy' : 'Copy YAML'} />
                </Button>
              </div>
              <pre className="overflow-x-auto p-3 font-mono text-xs leading-relaxed text-foreground">
                {yamlContent}
              </pre>
            </div>
          )}
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between gap-2 border-t border-border bg-secondary/20 px-4 py-2.5">
        <span className="font-mono text-[11px] text-muted-foreground">
          <Translated text={suggestion.conflict
            ? 'Xử lý cảnh báo trùng tên trước khi lưu'
            : 'Chỉ khả dụng để truy vấn sau khi được phê duyệt'} />
        </span>

        {/* ⛔ No Save/Submit while the conflict strip is unresolved — user must clarify first */}
        {!suggestion.conflict &&
          (action === 'submit_metric_request' ? (
            isApproved || isSaved ? (
              <Button
                size="sm"
                variant="secondary"
                className="h-8 gap-1.5 text-xs text-emerald-600 dark:text-emerald-400"
                disabled
              >
                <Check className="h-3.5 w-3.5" />
                <Translated text={"Đã được Data Lead duyệt"} />
              </Button>
            ) : isSubmitted ? (
              <Button
                size="sm"
                variant="secondary"
                className="h-8 gap-1.5 text-xs text-emerald-600 dark:text-emerald-400"
                disabled
              >
                <Check className="h-3.5 w-3.5" />
                <Translated text={"Đã gửi cho Data Lead"} />
              </Button>
            ) : (
              <Button
                size="sm"
                className="h-8 gap-1.5 text-xs cursor-pointer"
                onClick={() => void handleSubmitRequest()}
                disabled={saving || !suggestion.proposal_id || suggestion.review?.status !== 'pass'}
              >
                <Save className="h-3.5 w-3.5" />
                <Translated text={saving ? 'Đang gửi...' : 'Gửi Data Lead xem xét'} />
              </Button>
            )
          ) : isSaved ? (
            <Button
              size="sm"
              variant="secondary"
              className="h-8 gap-1.5 text-xs text-emerald-600 dark:text-emerald-400 cursor-pointer"
              onClick={onOpenCatalog}
            >
              <Check className="h-3.5 w-3.5" />
              <Translated text={"Đã lưu — mở catalog"} />
            </Button>
          ) : (
            <Button
              size="sm"
              className="h-8 gap-1.5 text-xs cursor-pointer"
              onClick={() => void handleSave()}
              disabled={saving || !suggestion.proposal_id || suggestion.review?.status !== 'pass'}
            >
              <Save className="h-3.5 w-3.5" />
              <Translated text={saving ? 'Đang lưu...' : 'Lưu vào Semantic Layer'} />
            </Button>
          ))}
      </div>
    </div>
  );
}
