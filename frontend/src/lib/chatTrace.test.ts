import { describe, expect, it } from 'vitest';
import { appendTraceEvent, readSse, traceSteps, TraceEvent } from './chatTrace';

import { traceFixture } from '@/test/chatTraceFixture';

describe('chat trace', () => {
  it('parses every byte boundary, Vietnamese UTF-8, CRLF, heartbeats, and multiline data', async () => {
    const source = ': heartbeat\r\n\r\nevent: progress\r\ndata: {"label":\r\ndata: "Đang xử lý"}\r\n\r\nevent: result\ndata: {"ok":true}\n\n';
    const bytes = new TextEncoder().encode(source);
    const stream = new ReadableStream<Uint8Array>({ start(controller) {
      for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
      controller.close();
    } });
    const frames = [];
    for await (const frame of readSse(stream)) frames.push(frame);
    expect(frames).toEqual([
      { event: 'progress', data: { label: 'Đang xử lý' } }, { event: 'result', data: { ok: true } },
    ]);
  });

  it('deduplicates events and retains separate invocations of the same node', () => {
    const finished: TraceEvent = { ...traceFixture.events[1], seq: 3, status: 'finished', duration_ms: 2100 };
    const trace = appendTraceEvent(traceFixture, finished);
    expect(appendTraceEvent(trace, finished)).toBe(trace);
    const repeated = appendTraceEvent(trace, { ...finished, seq: 4, step_id: 'step-2' });
    expect(traceSteps(repeated).map((step) => [step.step_id, step.status])).toEqual([
      ['step-1', 'finished'], ['step-2', 'finished'],
    ]);
  });
});
