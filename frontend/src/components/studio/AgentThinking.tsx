'use client';

import { ChevronDown, ChevronRight, GitBranch, Loader2, CheckCircle2, CircleAlert } from 'lucide-react';
import { useEffect, useId, useState } from 'react';
import { ExecutionTrace, TraceEvent, traceSteps } from '@/lib/chatTrace';
import { useLanguage } from '@/context/LanguageContext';
import { Button } from '@/components/ui/button';

const AGENT_NAMES: Record<string, string> = {
  orchestrator: 'Orchestrator', chitchat: 'Chitchat', data_assistant: 'Data Assistant',
  metric_coordinator: 'Điều phối metric', metric_suggest: 'Metric Designer', metric_validate: 'Kiểm tra kỹ thuật',
  metric_review: 'Data Lead Reviewer AI', metric_repair: 'Metric Designer sửa', context: 'Chuẩn bị schema', semantic_parse: 'Semantic Parse',
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
  if (status === 'started') return <Loader2 aria-hidden className="h-3.5 w-3.5 shrink-0 animate-spin text-blue-500 motion-reduce:animate-none" />;
  if (status === 'failed') return <CircleAlert aria-hidden className="h-3.5 w-3.5 shrink-0 text-red-500" />;
  return <CheckCircle2 aria-hidden className="h-3.5 w-3.5 shrink-0 text-emerald-500" />;
}

export function ThinkingSteps({ trace, node }: { trace: ExecutionTrace; node?: string }) {
  const { t, translate } = useLanguage();
  const steps = traceSteps(trace).filter((step) => !node || step.node === node || (
    node === 'sql' && step.action?.startsWith('sql_')
  ));
  return <ol className="space-y-3 text-xs">
    {steps.map((step) => <li key={step.step_id} className="flex items-start gap-2">
      <StepStatus status={step.status} />
      <div className="min-w-0 flex-1">
        <div className="font-medium">{AGENT_NAMES[step.node] || t('System', 'Hệ thống')}</div>
        <p className="mt-0.5 text-muted-foreground">{translate(step.summary)}</p>
        <span className="sr-only">{step.status === 'started' ? t('Running', 'Đang chạy') : step.status === 'failed' ? t('Error', 'Có lỗi') : t('Completed', 'Hoàn tất')}</span>
      </div>
      <TraceDuration key={`${step.step_id}:${step.status}:${trace.elapsed_ms}`}
        milliseconds={step.duration_ms ?? Math.max(0, trace.elapsed_ms - step.elapsed_ms)}
        running={step.status === 'started' && trace.status === 'running'} />
    </li>)}
    {!steps.length && <li className="text-muted-foreground">{t('This step has not run.', 'Bước này chưa chạy.')}</li>}
  </ol>;
}

export function AgentThinking({ trace, reconnecting, onOpenGraph }: {
  trace: ExecutionTrace; reconnecting?: boolean; onOpenGraph: (trigger: HTMLButtonElement) => void;
}) {
  const [open, setOpen] = useState(false);
  const contentId = useId();
  const { t } = useLanguage();
  const status = reconnecting ? t('Reconnecting', 'Đang kết nối lại') : {
    running: t('Processing', 'Đang xử lý'), completed: t('Completed', 'Hoàn tất'),
    needs_clarification: t('Needs clarification', 'Cần làm rõ'), error: t('Error', 'Có lỗi'),
    partial: t('Partially completed', 'Hoàn tất một phần'),
  }[trace.status];
  return <div className="w-full rounded-lg border border-border bg-card/60 text-xs">
    <div className="flex flex-wrap items-center justify-between gap-1 px-2 py-1">
      <button type="button" aria-expanded={open} aria-controls={contentId}
        onClick={() => setOpen(!open)} className="flex min-h-9 items-center gap-1.5 rounded px-1 text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring">
        {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        <span>Thinking · <span aria-live="polite">{status}</span> · </span>
        <TraceDuration key={`${trace.run_id}:${trace.elapsed_ms}:${trace.status}`}
          milliseconds={trace.elapsed_ms} running={trace.status === 'running' && !reconnecting} />
      </button>
      <Button type="button" variant="ghost" size="sm" className="gap-1.5 text-xs"
        onClick={(event) => onOpenGraph(event.currentTarget)}>
        <GitBranch className="h-3.5 w-3.5" />{t('Agent flow', 'Luồng agent')}
      </Button>
    </div>
    {open && <div id={contentId} className="border-t border-border p-3"><ThinkingSteps trace={trace} /></div>}
  </div>;
}
