'use client';

import { useEffect, useId, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import type { KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent } from 'react';
import { Cog, X } from 'lucide-react';
import { BotMessageSquareIcon } from '@/components/ui/BotMessageSquareIcon';
import { ExecutionTrace, traceSteps } from '@/lib/chatTrace';
import { cn } from '@/lib/utils';
import { useLanguage } from '@/context/LanguageContext';
import { TraceDuration } from './AgentThinking';

const NODES = [
  { id: 'request', name: 'Yêu cầu', en: 'Request', stage: 0 },
  { id: 'orchestrator', name: 'Orchestrator Agent', en: 'Orchestrator Agent', stage: 1, agent: true },
  { id: 'chitchat', name: 'Conversation Agent', en: 'Conversation Agent', stage: 2, agent: true },
  { id: 'data_assistant', name: 'Data Assistant Agent', en: 'Data Assistant Agent', stage: 2, agent: true },
  { id: 'metric_coordinator', name: 'Metric Workflow Coordinator', en: 'Metric Workflow Coordinator', stage: 2 },
  { id: 'metric_suggest', name: 'Metric Designer Agent', en: 'Metric Designer Agent', stage: 3, agent: true },
  { id: 'metric_validate', name: 'Kiểm tra kỹ thuật', en: 'Technical validation', stage: 4 },
  { id: 'metric_provider_wait', name: 'Đợi thử lại', en: 'Wait to retry', stage: 5 },
  { id: 'metric_review', name: 'Metric Reviewer Agent', en: 'Metric Reviewer Agent', stage: 5, agent: true },
  { id: 'metric_review_decision', name: 'Đánh giá nghiệp vụ', en: 'Business review', stage: 6 },
  { id: 'metric_repair', name: 'Sửa theo phản hồi', en: 'Metric repair', stage: 6 },
  { id: 'metric_conclude', name: 'Coordinator kết luận', en: 'Coordinator decision', stage: 7 },
  { id: 'semantic_parse', name: 'Semantic Query Parser Agent', en: 'Semantic Query Parser Agent', stage: 2, agent: true },
  { id: 'context', name: 'Chuẩn bị ngữ cảnh', en: 'Prepare context', stage: 3 },
  { id: 'dedupe', name: 'Kiểm tra trùng lặp', en: 'Check duplicates', stage: 4 },
  { id: 'metric_generation', name: 'Sinh metric', en: 'Generate metric', stage: 5 },
  { id: 'metric_generation_retry', name: 'Thử sinh lại', en: 'Retry generation', stage: 6 },
  { id: 'sql', name: 'Biên dịch · SQL', en: 'Compile · SQL', stage: 3 },
  { id: 'sql_execute', name: 'Thực thi truy vấn', en: 'Execute query', stage: 4 },
  { id: 'out_of_scope', name: 'Ngoài phạm vi', en: 'Out of scope', stage: 2 },
  { id: 'clarification', name: 'Cần làm rõ', en: 'Clarification', stage: 7 },
  { id: 'response', name: 'Phản hồi', en: 'Response', stage: 8 },
];

function subscribeViewport(listener: () => void) {
  window.addEventListener('resize', listener);
  return () => window.removeEventListener('resize', listener);
}

function nodeStatus(trace: ExecutionTrace, node: string): string {
  if (node === 'request') return 'completed';
  const steps = traceSteps(trace).filter((step) => step.node === node || (node === 'sql' && step.action?.startsWith('sql_')));
  if (steps.some((step) => step.status === 'started')) return 'running';
  if (steps.some((step) => step.status === 'failed')) return 'error';
  if (steps.length || trace.events.some((event) => event.source === node || event.target === node)) return 'completed';
  return 'idle';
}

export function AgentFlowPanel({ trace, title, onClose, trigger, reconnecting }: {
  trace: ExecutionTrace; title: string; onClose: () => void; trigger: HTMLButtonElement | null; reconnecting?: boolean;
}) {
  const { t, translate } = useLanguage();
  const [selected, setSelected] = useState('orchestrator');
  const [panelWidth, setPanelWidth] = useState(440);
  const [graphSize, setGraphSize] = useState({ width: 400, height: 500 });
  const resizeStart = useRef<{ x: number; width: number } | null>(null);
  const panelRef = useRef<HTMLElement>(null);
  const graphRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const headingId = useId();
  const markerId = useId().replaceAll(':', '');
  const mobile = useSyncExternalStore(subscribeViewport, () => window.matchMedia('(max-width: 1023px)').matches, () => false);
  const visibleNodes = useMemo(() => {
    const firstSeen = new Map<string, number>();
    trace.events.forEach((event, index) => {
      const touched = event.kind === 'transition'
        ? [event.source, event.target]
        : [event.node === 'sql' || event.action?.startsWith('sql_') ? 'sql' : event.node];
      touched.forEach((id) => {
        if (id && NODES.some((node) => node.id === id) && !firstSeen.has(id)) firstSeen.set(id, index);
      });
    });
    firstSeen.set('request', -1);
    if (trace.status !== 'running') firstSeen.set('response', trace.events.length);
    return NODES
      .filter((node) => firstSeen.has(node.id))
      .sort((a, b) => (firstSeen.get(a.id)! - firstSeen.get(b.id)!) || NODES.indexOf(a) - NODES.indexOf(b));
  }, [trace]);
  const visibleNodeIds = new Set(visibleNodes.map((node) => node.id));
  const graphWidth = graphSize.width;
  const graphHeight = graphSize.height;
  const graphContentWidth = Math.max(graphWidth, 120 + Math.max(0, visibleNodes.length - 1) * 136);
  const graphPositions = new Map(visibleNodes.map((node, index) => {
    return [node.id, { x: 60 + index * 136, y: graphHeight / 2 }] as const;
  }));
  const edges = [...new Map(trace.events
    .filter((event) => event.kind === 'transition'
      && visibleNodeIds.has(event.source || '') && visibleNodeIds.has(event.target || ''))
    .map((event) => [`${event.source}:${event.target}`, [event.source!, event.target!] as const])).values()];
  const selectedNode = visibleNodeIds.has(selected) ? selected : visibleNodes[0]?.id || 'request';
  const resizePanel = (event: ReactPointerEvent<HTMLDivElement>) => {
    const start = resizeStart.current;
    if (!start) return;
    const maxWidth = Math.min(720, window.innerWidth * 0.75);
    setPanelWidth(Math.min(maxWidth, Math.max(320, start.width + start.x - event.clientX)));
  };
  const finishResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    resizeStart.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };
  const handleResizeKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
    event.preventDefault();
    const maxWidth = Math.min(720, window.innerWidth * 0.75);
    setPanelWidth((width) => Math.min(maxWidth, Math.max(320, width + (event.key === 'ArrowLeft' ? 16 : -16))));
  };
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
  useEffect(() => {
    const graph = graphRef.current;
    if (!graph || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      if (width > 0 && height > 0) {
        setGraphSize((current) => current.width === width && current.height === height
          ? current
          : { width, height });
      }
    });
    observer.observe(graph);
    return () => observer.disconnect();
  }, []);
  return <aside ref={panelRef} aria-labelledby={headingId} role={mobile ? 'dialog' : 'complementary'} aria-modal={mobile || undefined}
    style={{ width: mobile ? undefined : panelWidth }}
    className="fixed inset-0 z-50 flex min-h-0 min-w-0 flex-col overflow-hidden overscroll-contain border-l border-border bg-background shadow-xl lg:relative lg:z-auto lg:w-[440px] lg:shrink-0 lg:shadow-none">
    {!mobile && <div role="separator" aria-orientation="vertical"
      aria-label={t('Resize agent flow panel', 'Thay đổi kích thước luồng agent')}
      aria-valuemin={320} aria-valuemax={Math.min(720, Math.round(window.innerWidth * 0.75))}
      aria-valuenow={panelWidth} tabIndex={0}
      onPointerDown={(event) => {
        event.preventDefault();
        resizeStart.current = { x: event.clientX, width: panelWidth };
        event.currentTarget.setPointerCapture(event.pointerId);
      }}
      onPointerMove={resizePanel} onPointerUp={finishResize} onPointerCancel={finishResize}
      onKeyDown={handleResizeKeyDown}
      className="absolute inset-y-0 left-0 z-10 hidden w-2 -translate-x-1/2 cursor-col-resize touch-none lg:block before:absolute before:inset-y-0 before:left-1/2 before:w-px before:bg-transparent hover:before:bg-primary focus-visible:before:bg-primary focus-visible:outline-none"
    />}
    <div className="flex shrink-0 items-start justify-between gap-3 border-b border-border p-4">
      <div className="min-w-0">
        <h2 id={headingId} className="font-semibold">{t('Agent flow', 'Luồng agent')}</h2>
        <p className="mt-1 break-words text-xs text-muted-foreground">{title}</p>
        <div className="mt-1 text-xs text-muted-foreground">{reconnecting && <span>{t('Reconnecting', 'Đang kết nối lại')} · </span>}<TraceDuration key={`${trace.run_id}:${trace.elapsed_ms}:${trace.status}`} milliseconds={trace.elapsed_ms} running={trace.status === 'running' && !reconnecting} /></div>
      </div>
      <button ref={closeRef} type="button" onClick={onClose} aria-label={t('Close agent flow', 'Đóng luồng agent')}
        className="rounded p-2 hover:bg-secondary focus-visible:outline-2 focus-visible:outline-ring"><X className="h-4 w-4" /></button>
    </div>
    <div className="flex min-h-0 flex-1 flex-col px-3 py-2">
      <div ref={graphRef} className="relative mx-auto min-h-0 w-full flex-1 overflow-x-auto overflow-y-hidden" aria-label={t('Agent execution graph', 'Sơ đồ thực thi agent')}>
        <div className="relative h-full" style={{ width: graphContentWidth }}>
        <svg viewBox={`0 0 ${graphContentWidth} ${graphHeight}`} preserveAspectRatio="none" aria-hidden className="absolute inset-0 h-full w-full">
          <defs><marker id={markerId} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" fill="context-stroke" /></marker></defs>
          {edges.map(([source, target]) => {
            const a = graphPositions.get(source)!;
            const b = graphPositions.get(target)!;
            const status = nodeStatus(trace, target);
            const forward = b.x >= a.x;
            const startX = a.x + (forward ? 44 : -44);
            const endX = b.x + (forward ? -44 : 44);
            const controlY = forward ? a.y : Math.max(24, a.y - 72);
            return <path key={`${source}-${target}`} data-taken="true" data-edge={`${source}-${target}`} data-edge-status={status}
              d={`M ${startX} ${a.y} C ${(startX + endX) / 2} ${controlY}, ${(startX + endX) / 2} ${controlY}, ${endX} ${b.y}`}
              fill="none" markerEnd={`url(#${markerId})`} strokeWidth={2} strokeDasharray={status === 'running' ? undefined : '5 5'}
              className={status === 'running' ? 'stroke-blue-500' : status === 'error' ? 'stroke-red-500' : 'stroke-emerald-500'} />;
          })}
        </svg>
        {visibleNodes.map((node) => {
          const status = nodeStatus(trace, node.id);
          const label = { idle: t('Not run', 'Chưa chạy'), running: t('Running', 'Đang chạy'), completed: t('Completed', 'Hoàn tất'), error: t('Error', 'Có lỗi') }[status];
          const selectedClass = selectedNode === node.id && 'ring-2 ring-ring/50';
          const statusClass = status === 'idle' ? 'border-border text-muted-foreground'
            : status === 'running' ? 'animate-pulse border-blue-500 text-blue-600 motion-reduce:animate-none dark:text-blue-400'
            : status === 'completed' ? 'border-emerald-500 text-emerald-700 dark:text-emerald-400'
            : 'border-red-500 text-red-600 dark:text-red-400';
          const position = graphPositions.get(node.id)!;
          const style = { left: `${position.x / graphContentWidth * 100}%`, top: `${position.y / graphHeight * 100}%` };
          const name = t(node.en, node.name);
          if (node.agent) return <div key={node.id} className="absolute flex w-[84px] -translate-x-1/2 -translate-y-1/2 flex-col items-center text-center text-[9px] leading-tight" style={style}>
            <button type="button" aria-label={`${name} · ${label}`} aria-pressed={selectedNode === node.id}
              onClick={() => setSelected(node.id)}
              className={cn('flex h-10 w-10 items-center justify-center rounded-full border-2 bg-card shadow-xs focus-visible:outline-2 focus-visible:outline-ring', statusClass, selectedClass)}>
              <BotMessageSquareIcon className="h-4 w-4" />
            </button>
            <span className="mt-1 line-clamp-3 font-medium">{name}</span>
            <span>{status === 'completed' ? '✓' : status === 'error' ? '!' : '◌'} {status === 'running' ? t('Running', 'Đang chạy') : label}</span>
          </div>;
          return <button type="button" key={node.id} data-node-kind="step" aria-pressed={selectedNode === node.id}
            aria-label={`${name} · ${label}`} onClick={() => setSelected(node.id)} style={style}
            className={cn('absolute flex w-[96px] -translate-x-1/2 -translate-y-1/2 flex-col items-center gap-1 border border-dashed bg-card px-1.5 py-2 text-center text-[10px] leading-tight shadow-xs focus-visible:outline-2 focus-visible:outline-ring',
              'rounded', selectedClass,
              status === 'idle' && 'border-border text-muted-foreground',
              status === 'running' && 'animate-pulse border-blue-500 text-blue-600 motion-reduce:animate-none dark:text-blue-400',
              status === 'completed' && 'border-emerald-500 text-emerald-700 dark:text-emerald-400',
              status === 'error' && 'border-red-500 text-red-600 dark:text-red-400')}>
            <span className="flex items-center justify-center gap-1 font-medium"><Cog className="h-3 w-3 shrink-0" />{name}</span>
            <span>{status === 'completed' ? '✓ ' : status === 'error' ? '! ' : status === 'running' ? '◌ ' : '○ '}{label}</span>
          </button>;
        }) }
        </div>
      </div>
      <p className="shrink-0 pt-1 text-[10px] text-muted-foreground">{t('Agents: solid border · System steps: dashed border · Active route: solid line · Completed route: dashed line', 'Agent: viền liền · Bước hệ thống: viền nét đứt · Luồng đang chạy: đường liền · Luồng đã chạy: đường gạch')}</p>
      <div className="max-h-[22vh] shrink-0 overflow-hidden border-t border-border px-3 py-2">
        <h3 className="truncate text-xs font-semibold">{t(NODES.find((node) => node.id === selectedNode)!.en, NODES.find((node) => node.id === selectedNode)!.name)}</h3>
        {traceSteps(trace).filter((step) => step.node === selectedNode || (selectedNode === 'sql' && step.action?.startsWith('sql_'))).slice(-1).map((step) =>
          <div key={step.step_id} className="mt-1 flex items-start gap-2 text-[11px]">
            <span className="shrink-0">{step.status === 'started' ? '◌' : step.status === 'failed' ? '!' : '✓'}</span>
            <p className="line-clamp-2 min-w-0 text-muted-foreground">{translate(step.summary)}</p>
          </div>)}
        {nodeStatus(trace, selectedNode) === 'idle' && <p className="mt-1 text-[11px] text-muted-foreground">{t('This step has not run.', 'Bước này chưa chạy.')}</p>}
      </div>
    </div>
  </aside>;
}
