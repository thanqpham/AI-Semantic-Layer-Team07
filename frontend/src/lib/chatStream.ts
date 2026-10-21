import { appendTraceEvent, ExecutionTrace, readSse, TraceEvent } from './chatTrace';

export interface ChatProgressOptions {
  signal: AbortSignal;
  onTrace: (trace: ExecutionTrace) => void;
  onReconnecting: (reconnecting: boolean) => void;
}

export class ChatStreamError extends Error {
  constructor(message: string, public trace?: ExecutionTrace) { super(message); }
}

function retryDelay(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    signal.throwIfAborted();
    const abort = () => { clearTimeout(timer); reject(signal.reason); };
    const timer = setTimeout(() => { signal.removeEventListener('abort', abort); resolve(); }, ms);
    signal.addEventListener('abort', abort, { once: true });
  });
}

export async function sendChatStream<T>(url: string, init: RequestInit, options: ChatProgressOptions): Promise<T> {
  let trace: ExecutionTrace | undefined;
  for (let attempt = 0; ; attempt++) {
    options.signal.throwIfAborted();
    try {
      const response = await fetch(url, { ...init, signal: options.signal });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new ChatStreamError(typeof error.detail === 'string' ? error.detail : 'Không thể xử lý yêu cầu chat');
      }
      if (!response.body) throw new Error('Missing response stream');
      options.onReconnecting(false);
      for await (const frame of readSse(response.body)) {
        if (frame.event === 'snapshot') trace = frame.data as ExecutionTrace;
        if (frame.event === 'progress' && trace) trace = appendTraceEvent(trace, frame.data as TraceEvent);
        if (frame.event === 'result') return frame.data as T;
        if (frame.event === 'error') {
          const error = frame.data as { message: string; execution_trace?: ExecutionTrace };
          throw new ChatStreamError(error.message, error.execution_trace);
        }
        if (trace) options.onTrace(trace);
      }
      throw new Error('Stream ended before result');
    } catch (error) {
      if (options.signal.aborted || error instanceof ChatStreamError) throw error;
      if (attempt >= 4) throw new ChatStreamError('Mất kết nối. Tải lại trang để tiếp tục yêu cầu.', trace);
      options.onReconnecting(true);
      await retryDelay(Math.min(1000 * 2 ** attempt, 8000), options.signal);
    }
  }
}
