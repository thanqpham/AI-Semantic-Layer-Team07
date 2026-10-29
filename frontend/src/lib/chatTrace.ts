export type TraceStatus = 'running' | 'completed' | 'partial' | 'needs_clarification' | 'error';

export interface TraceEvent {
  seq: number;
  at: string;
  elapsed_ms: number;
  kind: 'step' | 'transition';
  step_id: string;
  node: string;
  action?: string;
  status: 'started' | 'finished' | 'failed';
  summary: string;
  outcome_summary?: string;
  duration_ms?: number;
  source?: string;
  target?: string;
  candidate_id?: string | null;
  attempt?: number | null;
  validation_errors?: { field: string; type: string; message: string }[];
}

export interface ExecutionTrace {
  run_id: string;
  status: TraceStatus;
  started_at: string;
  finished_at: string | null;
  elapsed_ms: number;
  events: TraceEvent[];
}

export function appendTraceEvent(trace: ExecutionTrace, event: TraceEvent): ExecutionTrace {
  if (trace.events.some((item) => item.seq === event.seq)) return trace;
  return { ...trace, elapsed_ms: event.elapsed_ms, events: [...trace.events, event] };
}

export function traceSteps(trace: ExecutionTrace): TraceEvent[] {
  const steps = new Map<string, TraceEvent>();
  for (const event of trace.events) {
    if (event.kind === 'step') steps.set(event.step_id, { ...steps.get(event.step_id), ...event });
  }
  return [...steps.values()];
}

const AGENT_IDS = new Set(['orchestrator', 'chitchat', 'data_assistant', 'metric_suggest', 'metric_review', 'semantic_parse']);

export function agentId(node: string | undefined): string | undefined {
  const id = node === 'metric_repair' ? 'metric_suggest' : node;
  return id && AGENT_IDS.has(id) ? id : undefined;
}

export function traceAgents(trace: ExecutionTrace): TraceEvent[] {
  const agents = new Map<string, TraceEvent[]>();
  for (const step of traceSteps(trace)) {
    const id = agentId(step.node);
    if (id) agents.set(id, [...(agents.get(id) || []), step]);
  }
  return [...agents].map(([id, steps]) => {
    const main = steps.filter((step) => agentId(step.action) === id && step.action === step.node);
    const latest = (main.length ? main : steps).at(-1)!;
    const outcome = [...steps].reverse().find((step) => step.outcome_summary?.trim())?.outcome_summary;
    return { ...latest, node: id, step_id: id, outcome_summary: outcome };
  });
}

/** Parse SSE across arbitrary UTF-8 chunks, including CRLF and multiline data. */
export async function* readSse(body: ReadableStream<Uint8Array>): AsyncGenerator<{ event: string; data: unknown }> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      let boundary: RegExpExecArray | null;
      while ((boundary = /\r?\n\r?\n/.exec(buffer))) {
        const frame = buffer.slice(0, boundary.index);
        buffer = buffer.slice(boundary.index + boundary[0].length);
        const lines = frame.split(/\r?\n/);
        const data = lines.filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trimStart()).join('\n');
        if (data) yield {
          event: lines.find((line) => line.startsWith('event:'))?.slice(6).trim() || 'message',
          data: JSON.parse(data),
        };
      }
      if (done) break;
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
