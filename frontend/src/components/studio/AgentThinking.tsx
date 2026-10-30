'use client';

import { ChevronDown, ChevronRight, GitBranch, Loader2, CheckCircle2, CircleAlert } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';
import { ExecutionTrace, TraceEvent, traceAgents, traceSteps } from '@/lib/chatTrace';
import { useLanguage } from '@/context/LanguageContext';
import { Button } from '@/components/ui/button';
import { AgentFlowCanvas } from './AgentFlowCanvas';

const AGENT_NAMES: Record<string, string> = {
  orchestrator: 'Orchestrator Agent', chitchat: 'Conversation Agent', data_assistant: 'Data Assistant Agent',
  metric_coordinator: 'Metric Workflow Coordinator', metric_suggest: 'Metric Designer Agent', metric_validate: 'Kiểm tra kỹ thuật',
  metric_review: 'Metric Reviewer Agent', metric_repair: 'Metric Designer Agent', context: 'Chuẩn bị schema', semantic_parse: 'Semantic Query Parser Agent',
};

export function TraceDuration({ milliseconds, running = false }: { milliseconds: number; running?: boolean }) {
  const [extra, setExtra] = useState(0);
  useEffect(() => {
    if (!running) return;
    const started = performance.now();
    const timer = window.setInterval(() => setExtra(performance.now() - started), 1000);
    return () => window.clearInterval(timer);
  }, [running]);
  const seconds = Math.max(0, milliseconds + (running ? extra : 0)) / 1000;
  const duration = seconds < 1 ? `${Number(seconds.toFixed(3))} s`
    : seconds < 60 ? `${Math.floor(seconds)} s`
    : `${Math.floor(seconds / 60)} m ${Math.floor(seconds % 60)} s`;
  return <span className="tabular-nums">{duration}</span>;
}

export function StepStatus({ status }: { status: TraceEvent['status'] }) {
  if (status === 'started') return <span aria-hidden className="h-3.5 w-3.5 shrink-0 overflow-hidden"><Loader2 className="h-full w-full animate-spin text-blue-500 motion-reduce:animate-none" /></span>;
  if (status === 'failed') return <CircleAlert aria-hidden className="h-3.5 w-3.5 shrink-0 text-red-500" />;
  return <CheckCircle2 aria-hidden className="h-3.5 w-3.5 shrink-0 text-emerald-500" />;
}

export function ThinkingSteps({ trace, node }: { trace: ExecutionTrace; node?: string }) {
  const { t } = useLanguage();
  const steps = traceSteps(trace).filter((step) => !node || step.node === node || (
    node === 'sql' && step.action?.startsWith('sql_')
  ));
  return <ol className="space-y-3 text-xs">
    {steps.map((step, index) => <li key={step.step_id} className="relative flex items-start gap-2">
      {index < steps.length - 1 && <span aria-hidden className="absolute left-[7px] top-4 h-[calc(100%+0.75rem)] border-l border-border" />}
      <StepStatus status={step.status} />
      <div className="min-w-0 flex-1">
        <div className="font-medium">{AGENT_NAMES[step.node] || t('System', 'Hệ thống')}</div>
        {step.summary?.trim() && <p className="mt-1 break-words text-muted-foreground">{step.summary}</p>}
        <span className="sr-only">{step.status === 'started' ? t('Running', 'Đang chạy') : step.status === 'failed' ? t('Error', 'Có lỗi') : t('Completed', 'Hoàn tất')}</span>
      </div>
      <TraceDuration key={`${step.step_id}:${step.status}:${trace.elapsed_ms}`}
        milliseconds={step.duration_ms ?? Math.max(0, trace.elapsed_ms - step.elapsed_ms)}
        running={step.status === 'started' && trace.status === 'running'} />
    </li>)}
    {!steps.length && <li className="text-muted-foreground">{t('This step has not run.', 'Bước này chưa chạy.')}</li>}
  </ol>;
}

function AgentTimelineItem({
  event,
  trace,
  reconnecting,
  t,
  onToggleDetails,
}: {
  event: TraceEvent;
  trace: ExecutionTrace;
  reconnecting?: boolean;
  t: (en: string, vi: string) => string;
  onToggleDetails?: (open: boolean) => void;
}) {
  return (
    <li key={event.step_id} className="flex items-start gap-2">
      <StepStatus status={event.status} />
      <div className="min-w-0 flex-1">
        <details
          className="group"
          onToggle={(e) => {
            onToggleDetails?.(e.currentTarget.open);
          }}
        >
          <summary
            aria-label={`${t('View explanation', 'Xem giải thích')}: ${AGENT_NAMES[event.node] || t('System', 'Hệ thống')}`}
            className="flex w-fit cursor-pointer list-none items-center gap-1 rounded font-medium hover:text-primary focus-visible:outline-2 focus-visible:outline-ring [&::-webkit-details-marker]:hidden"
          >
            {AGENT_NAMES[event.node] || t('System', 'Hệ thống')}
            <ChevronRight
              aria-hidden
              className="h-3.5 w-3.5 text-muted-foreground transition-transform group-open:rotate-90 motion-reduce:transition-none"
            />
          </summary>
          <p className="mt-1 whitespace-pre-wrap break-words text-foreground [overflow-wrap:anywhere]">
            {event.outcome_summary?.trim() || t('No explanation available', 'Chưa có giải thích')}
          </p>
        </details>
        <span className="sr-only">
          {event.status === 'started'
            ? t('Running', 'Đang chạy')
            : event.status === 'failed'
              ? t('Error', 'Có lỗi')
              : t('Completed', 'Hoàn tất')}
        </span>
      </div>
      {(event.status === 'started' || event.duration_ms !== undefined) && <TraceDuration
        key={`${event.step_id}:${event.status}:${trace.elapsed_ms}:${reconnecting}`}
        milliseconds={event.duration_ms ?? Math.max(0, trace.elapsed_ms - event.elapsed_ms)}
        running={event.status === 'started' && trace.status === 'running' && !reconnecting}
      />}
    </li>
  );
}

function AgentAnswerSection({
  answer,
  renderAnswer,
  t,
}: {
  answer: string;
  renderAnswer?: (answer: string) => React.ReactNode;
  t: (en: string, vi: string) => string;
}) {
  return (
    <section
      data-thinking-answer
      aria-label={t('Final answer', 'Câu trả lời')}
      className="border-t border-border pt-3 overflow-x-hidden"
    >
      <h3 className="mb-2 font-semibold">{t('Final answer', 'Câu trả lời')}</h3>
      {renderAnswer ? renderAnswer(answer) : <p className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{answer}</p>}
    </section>
  );
}

export function AgentThinking({
  trace,
  reconnecting,
  answer,
  answerStreaming,
  renderAnswer,
  onOpenGraph,
}: {
  trace: ExecutionTrace;
  reconnecting?: boolean;
  answer?: string;
  answerStreaming?: boolean;
  renderAnswer?: (answer: string) => React.ReactNode;
  onOpenGraph?: (trigger: HTMLButtonElement) => void;
}) {
  const [open, setOpen] = useState(false);
  const [showFlow, setShowFlow] = useState(false);
  const contentId = useId();
  const flowId = useId();
  const timelineRef = useRef<HTMLDivElement>(null);
  const shouldFollowRef = useRef(true);
  const lastSeqRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    const lastSeq = trace.events.at(-1)?.seq;
    if (lastSeq === lastSeqRef.current) return;
    lastSeqRef.current = lastSeq;
    const container = timelineRef.current;
    if (container && shouldFollowRef.current) container.scrollTop = container.scrollHeight;
  }, [trace.events]);

  const handleToggleDetails = (isOpen: boolean) => {
    if (isOpen) {
      shouldFollowRef.current = false;
    } else {
      const container = timelineRef.current;
      if (container) {
        shouldFollowRef.current =
          container.scrollHeight - container.scrollTop - container.clientHeight < 24;
      }
    }
  };

  const { t } = useLanguage();
  const events = traceAgents(trace);
  const status = reconnecting
    ? t('Reconnecting', 'Đang kết nối lại')
    : {
        running: t('Processing', 'Đang xử lý'),
        completed: t('Completed', 'Hoàn tất'),
        needs_clarification: t('Needs clarification', 'Cần làm rõ'),
        error: t('Error', 'Có lỗi'),
        partial: t('Partially completed', 'Hoàn tất một phần'),
      }[trace.status];

  const handleToggleFlow = (event: React.MouseEvent<HTMLButtonElement>) => {
    if (!open) {
      setOpen(true);
      setShowFlow(true);
    } else {
      setShowFlow((prev) => !prev);
    }
    onOpenGraph?.(event.currentTarget);
  };

  return (
    <div className="w-full rounded-lg border border-border bg-card/60 text-xs">
      <div className="flex flex-wrap items-center justify-between gap-1 px-2 py-1">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={contentId}
          onClick={() => setOpen(!open)}
          className="flex min-h-8 items-center gap-1.5 rounded px-1 text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"
        >
          {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          <span>Thinking · <span aria-live="polite">{status}</span> · </span>
          <TraceDuration
            key={`${trace.run_id}:${trace.elapsed_ms}:${trace.status}`}
            milliseconds={trace.elapsed_ms}
            running={trace.status === 'running' && !reconnecting}
          />
        </button>
        <Button
          type="button"
          variant={open && showFlow ? 'secondary' : 'ghost'}
          size="sm"
          className="gap-1.5 text-xs"
          aria-expanded={open && showFlow}
          aria-controls={open && showFlow ? flowId : undefined}
          onClick={handleToggleFlow}
        >
          <GitBranch className="h-3.5 w-3.5" />
          {t('Agent flow', 'Luồng agent')}
        </Button>
      </div>
      {open && (
        <div
          id={contentId}
          className="space-y-3 border-t border-border p-3"
        >
          {showFlow && (
            <div id={flowId} className="w-full">
              <h4 className="sr-only">{t('Agent flow', 'Luồng agent')}</h4>
              <AgentFlowCanvas trace={trace} reconnecting={reconnecting} />
            </div>
          )}
          <div
            ref={timelineRef}
            className="max-h-60 overflow-y-auto overflow-x-hidden pr-1 [scrollbar-gutter:stable] [scrollbar-width:thin] overscroll-contain"
            onScroll={(event) => {
              const element = event.currentTarget;
              shouldFollowRef.current = element.scrollHeight - element.scrollTop - element.clientHeight < 24;
            }}
          >
            <ol aria-label={t('Live activity', 'Hoạt động trực tiếp')} className="space-y-3 text-xs">
              {events.map((event) => (
                <AgentTimelineItem
                  key={event.step_id}
                  event={event}
                  trace={trace}
                  reconnecting={reconnecting}
                  t={t}
                  onToggleDetails={handleToggleDetails}
                />
              ))}
            </ol>
          </div>
          {answerStreaming && answer?.trim() && (
            <AgentAnswerSection answer={answer} renderAnswer={renderAnswer} t={t} />
          )}
        </div>
      )}
    </div>
  );
}
