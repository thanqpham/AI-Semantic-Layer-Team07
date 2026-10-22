'use client';

import { useEffect, useId, useRef, useState, useSyncExternalStore } from 'react';
import { Bot, Cog, X } from 'lucide-react';
import { ExecutionTrace, traceSteps } from '@/lib/chatTrace';
import { cn } from '@/lib/utils';
import { useLanguage } from '@/context/LanguageContext';
import { ThinkingSteps, TraceDuration } from './AgentThinking';

const NODES = [
  { id: 'request', name: 'Yêu cầu', en: 'Request', x: 200, y: 24 },
  { id: 'orchestrator', name: 'Orchestrator', en: 'Orchestrator', x: 200, y: 94, agent: true },
  { id: 'chitchat', name: 'Chitchat', en: 'Chitchat', x: 72, y: 174, agent: true },
  { id: 'data_assistant', name: 'Data Assistant', en: 'Data Assistant', x: 200, y: 174, agent: true },
  { id: 'metric_suggest', name: 'Metric Suggest', en: 'Metric Suggest', x: 328, y: 174, agent: true },
  { id: 'metric_review', name: 'Thẩm định KPI', en: 'Metric Review', x: 328, y: 294, agent: true },
  { id: 'semantic_parse', name: 'Semantic Parse', en: 'Semantic Parse', x: 135, y: 254, agent: true },
  { id: 'out_of_scope', name: 'Ngoài phạm vi', en: 'Out of scope', x: 285, y: 254 },
  { id: 'sql', name: 'Biên dịch · SQL', en: 'Compile · SQL', x: 95, y: 334 },
  { id: 'clarification', name: 'Cần làm rõ', en: 'Clarification', x: 245, y: 334 },
  { id: 'response', name: 'Phản hồi', en: 'Response', x: 200, y: 424 },
];
const EDGES = [
  ['request', 'orchestrator'], ['orchestrator', 'chitchat'], ['orchestrator', 'data_assistant'],
  ['orchestrator', 'metric_suggest'], ['orchestrator', 'semantic_parse'], ['orchestrator', 'out_of_scope'],
  ['semantic_parse', 'sql'], ['semantic_parse', 'clarification'], ['chitchat', 'response'],
  ['data_assistant', 'response'], ['metric_suggest', 'metric_review'], ['metric_review', 'response'], ['metric_review', 'clarification'], ['sql', 'response'],
  ['clarification', 'response'], ['out_of_scope', 'response'],
];

function subscribeViewport(listener: () => void) {
  window.addEventListener('resize', listener);
  return () => window.removeEventListener('resize', listener);
}

function nodeStatus(trace: ExecutionTrace, node: string): string {
  const steps = traceSteps(trace).filter((step) => step.node === node || (node === 'sql' && step.action?.startsWith('sql_')));
  if (steps.some((step) => step.status === 'started')) return 'running';
  if (steps.some((step) => step.status === 'failed')) return 'error';
  if (steps.length || trace.events.some((event) => event.source === node || event.target === node)) return 'completed';
  return 'idle';
}

export function AgentFlowPanel({ trace, title, onClose, trigger, reconnecting }: {
  trace: ExecutionTrace; title: string; onClose: () => void; trigger: HTMLButtonElement | null; reconnecting?: boolean;
}) {
  const { t } = useLanguage();
  const [selected, setSelected] = useState('orchestrator');
  const panelRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const headingId = useId();
  const markerId = useId().replaceAll(':', '');
  const mobile = useSyncExternalStore(subscribeViewport, () => window.matchMedia('(max-width: 1023px)').matches, () => false);
  const actualEdges = trace.events.filter((event) => event.kind === 'transition'
    && NODES.some((node) => node.id === event.source) && NODES.some((node) => node.id === event.target))
    .map((event) => [event.source!, event.target!]);
  const edges = [...new Map([...EDGES, ...actualEdges].map((edge) => [edge.join(':'), edge])).values()];
  useEffect(() => {
    const chat = panelRef.current?.previousElementSibling;
    if (mobile) chat?.setAttribute('inert', '');
    closeRef.current?.focus({ preventScroll: true });
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); onClose(); }
      if (event.key !== 'Tab' || !mobile) return;
      const buttons = panelRef.current?.querySelectorAll<HTMLButtonElement>('button');
      if (!buttons?.length) return;
      const first = buttons[0], last = buttons[buttons.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', keydown);
    return () => {
      chat?.removeAttribute('inert');
      document.removeEventListener('keydown', keydown);
      if (trigger?.isConnected) trigger.focus({ preventScroll: true });
    };
  }, [onClose, trigger, mobile]);
  return <aside ref={panelRef} aria-labelledby={headingId} role={mobile ? 'dialog' : 'complementary'} aria-modal={mobile || undefined}
    className="fixed inset-0 z-50 flex min-h-0 min-w-0 flex-col overflow-y-auto overscroll-contain border-l border-border bg-background shadow-xl lg:static lg:z-auto lg:w-[440px] lg:shrink-0 lg:shadow-none">
    <div className="flex shrink-0 items-start justify-between gap-3 border-b border-border p-4">
      <div className="min-w-0">
        <h2 id={headingId} className="font-semibold">{t('Agent flow', 'Luồng agent')}</h2>
        <p className="mt-1 break-words text-xs text-muted-foreground">{title}</p>
        <div className="mt-1 text-xs text-muted-foreground">{reconnecting && <span>{t('Reconnecting', 'Đang kết nối lại')} · </span>}<TraceDuration key={`${trace.run_id}:${trace.elapsed_ms}:${trace.status}`} milliseconds={trace.elapsed_ms} running={trace.status === 'running' && !reconnecting} /></div>
      </div>
      <button ref={closeRef} type="button" onClick={onClose} aria-label={t('Close agent flow', 'Đóng luồng agent')}
        className="rounded p-2 hover:bg-secondary focus-visible:outline-2 focus-visible:outline-ring"><X className="h-4 w-4" /></button>
    </div>
    <div className="shrink-0 px-3 py-4">
      <div className="relative mx-auto aspect-[400/465] w-full max-w-[420px]" aria-label={t('Agent execution graph', 'Sơ đồ thực thi agent')}>
        <svg viewBox="0 0 400 465" aria-hidden className="absolute inset-0 h-full w-full overflow-visible">
          <defs><marker id={markerId} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" fill="context-stroke" /></marker></defs>
          {edges.map(([source, target]) => {
            const a = NODES.find((node) => node.id === source)!, b = NODES.find((node) => node.id === target)!;
            const taken = trace.events.some((event) => event.kind === 'transition' && event.source === source && event.target === target);
            const status = nodeStatus(trace, target);
            return <path key={`${source}-${target}`} data-taken={taken} data-edge={`${source}-${target}`}
              d={`M ${a.x} ${a.y + 20} C ${a.x} ${a.y + 50}, ${b.x} ${b.y - 50}, ${b.x} ${b.y - 20}`}
              fill="none" markerEnd={`url(#${markerId})`} strokeWidth={taken ? 2 : 1}
              className={!taken ? 'stroke-muted-foreground/20' : status === 'running' ? 'stroke-blue-500' : status === 'error' ? 'stroke-red-500' : 'stroke-emerald-500'} />;
          })}
        </svg>
        {NODES.map((node) => {
          const status = nodeStatus(trace, node.id);
          const label = { idle: t('Not run', 'Chưa chạy'), running: t('Running', 'Đang chạy'), completed: t('Completed', 'Hoàn tất'), error: t('Error', 'Có lỗi') }[status];
          return <button type="button" key={node.id} aria-pressed={selected === node.id}
            onClick={() => setSelected(node.id)} style={{ left: `${node.x / 4}%`, top: `${node.y / 4.65}%` }}
            className={cn('absolute flex w-[30%] -translate-x-1/2 -translate-y-1/2 flex-col items-center gap-0.5 border bg-card px-1 py-2 text-[10px] shadow-xs focus-visible:outline-2 focus-visible:outline-ring',
              node.agent ? 'rounded-lg' : 'rounded border-dashed', selected === node.id && 'ring-2 ring-ring/50',
              status === 'idle' && 'border-border text-muted-foreground',
              status === 'running' && 'animate-pulse border-blue-500 text-blue-600 motion-reduce:animate-none dark:text-blue-400',
              status === 'completed' && 'border-emerald-500 text-emerald-700 dark:text-emerald-400',
              status === 'error' && 'border-red-500 text-red-600 dark:text-red-400')}>
            <span className="flex items-center gap-1 font-medium">{node.agent ? <Bot className="h-3 w-3" /> : <Cog className="h-3 w-3" />}{t(node.en, node.name)}</span>
            <span>{status === 'completed' ? '✓ ' : status === 'error' ? '! ' : status === 'running' ? '◌ ' : '○ '}{label}</span>
          </button>;
        })}
      </div>
      <p className="text-[10px] text-muted-foreground">{t('Solid border: agent · Dashed border: system step', 'Viền liền: agent · Viền nét đứt: bước hệ thống')}</p>
    </div>
    <div className="shrink-0 break-words [overflow-wrap:anywhere] border-t border-border p-4">
      <h3 className="mb-3 text-sm font-semibold">{t(NODES.find((node) => node.id === selected)!.en, NODES.find((node) => node.id === selected)!.name)}</h3>
      {traceSteps(trace).some((step) => step.node === selected || (selected === 'sql' && step.action?.startsWith('sql_')))
        ? <ThinkingSteps trace={trace} node={selected} />
        : <p className="text-xs text-muted-foreground">{nodeStatus(trace, selected) === 'idle'
          ? t('This step has not run.', 'Bước này chưa chạy.')
          : t('Control flow passed through this step.', 'Luồng xử lý đã đi qua bước này.')}</p>}
    </div>
  </aside>;
}
