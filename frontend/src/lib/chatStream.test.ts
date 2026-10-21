import { afterEach, describe, expect, it, vi } from 'vitest';
import { ChatProgressOptions, ChatStreamError, sendChatStream } from './chatStream';
import { traceFixture } from '@/test/chatTraceFixture';

function response(frames: string) {
  return new Response(new ReadableStream({ start(controller) {
    controller.enqueue(new TextEncoder().encode(frames)); controller.close();
  } }), { headers: { 'Content-Type': 'text/event-stream' } });
}
function options(): ChatProgressOptions {
  return { signal: new AbortController().signal, onTrace: vi.fn(), onReconnecting: vi.fn() };
}
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe('chat streaming reconnect', () => {
  it('reuses the same request body after an interrupted stream and replaces its snapshot', async () => {
    vi.useFakeTimers();
    const fetch = vi.fn()
      .mockResolvedValueOnce(response(`event: snapshot\ndata: ${JSON.stringify(traceFixture)}\n\n`))
      .mockResolvedValueOnce(response(`event: snapshot\ndata: ${JSON.stringify({ ...traceFixture, elapsed_ms: 9000 })}\n\nevent: result\ndata: {"answer":"ok"}\n\n`));
    vi.stubGlobal('fetch', fetch);
    const callbacks = options();
    const pending = sendChatStream('/chat', { method: 'POST', body: '{"client_message_id":"stable"}' }, callbacks);
    await vi.advanceTimersByTimeAsync(1100);
    expect(await pending).toEqual({ answer: 'ok' });
    expect(fetch.mock.calls[1][1].body).toBe(fetch.mock.calls[0][1].body);
    expect(callbacks.onReconnecting).toHaveBeenCalledWith(true);
    expect(callbacks.onTrace).toHaveBeenLastCalledWith(expect.objectContaining({ elapsed_ms: 9000 }));
  });

  it('does not retry authorization failures or terminal agent errors', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(new Response('{"detail":"Forbidden"}', { status: 403 }));
    vi.stubGlobal('fetch', fetch);
    await expect(sendChatStream('/chat', {}, options())).rejects.toThrow('Forbidden');
    expect(fetch).toHaveBeenCalledTimes(1);
    fetch.mockResolvedValueOnce(response(`event: error\ndata: ${JSON.stringify({ message: 'Safe error', execution_trace: { ...traceFixture, status: 'error' } })}\n\n`));
    await expect(sendChatStream('/chat', {}, options())).rejects.toBeInstanceOf(ChatStreamError);
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it('aborts a reconnect wait when switching conversations', async () => {
    vi.useFakeTimers();
    const fetch = vi.fn().mockRejectedValue(new TypeError('offline'));
    vi.stubGlobal('fetch', fetch);
    const controller = new AbortController();
    const pending = sendChatStream('/chat', {}, { ...options(), signal: controller.signal });
    const rejected = expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    await vi.advanceTimersByTimeAsync(10);
    controller.abort();
    await rejected;
    await vi.advanceTimersByTimeAsync(9000);
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
