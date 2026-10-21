import { ChatClarificationSelection, getAuthHeader } from '@/lib/api';
import { parseJWTToken } from '@/lib/jwt';

export interface PendingChat {
  prompt: string;
  clientMessageId: string;
  sessionId: string | null;
  reuseMetricId?: number;
  selection?: ChatClarificationSelection;
}

export function pendingChatKey(dbId: number, sessionId: string | null): string {
  const headers = getAuthHeader();
  const token = headers.Authorization?.replace(/^Bearer /, '');
  const userId = token ? parseJWTToken(token)?.id : 'anonymous';
  return `pending-chat:${userId}:${headers['X-Organization-ID'] || ''}:${dbId}:${sessionId || 'new'}`;
}

export function readPendingChat(key: string): PendingChat | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(key) || 'null');
    if (value && typeof value.prompt === 'string' && typeof value.clientMessageId === 'string'
      && (value.sessionId === null || typeof value.sessionId === 'string')) return value;
  } catch {
    // A corrupt or unavailable browser store must not prevent opening chat.
  }
  return null;
}

export function storePendingChat(key: string, request: PendingChat | null): void {
  try {
    if (request) sessionStorage.setItem(key, JSON.stringify(request));
    else sessionStorage.removeItem(key);
  } catch {
    // Chat still works when browser storage is disabled, but cannot resume after reload.
  }
}
