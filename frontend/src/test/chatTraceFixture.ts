import { ExecutionTrace } from '@/lib/chatTrace';

export const traceFixture: ExecutionTrace = {
  run_id: 'run-1', status: 'running', started_at: '2026-10-22T00:00:00Z', finished_at: null,
  elapsed_ms: 2000, events: [
    { seq: 1, kind: 'transition', step_id: 'edge-1', node: 'orchestrator', source: 'request', target: 'orchestrator',
      at: '', elapsed_ms: 0, status: 'finished', summary: '' },
    { seq: 2, kind: 'step', step_id: 'step-1', node: 'orchestrator', action: 'orchestrator',
      at: '', elapsed_ms: 0, status: 'started', summary: 'Phân loại yêu cầu' },
  ],
};

