/**
 * Thin fetch wrapper. Attaches the current Supabase JWT to every request,
 * unwraps the error envelope, and returns typed bodies.
 */

import { supabase } from '@/auth/supabase';
import { config } from '@/config';
import type {
  APIErrorBody,
  Conversation,
  Message,
  MessagePair,
  Twin,
  TwinCreateIn,
  TwinProfilePatch,
  UUID,
} from './types';

export class APIError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly details?: Record<string, unknown>,
  ) {
    super(message);
  }
}

async function authHeaders(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  if (!token) throw new APIError(401, 'unauthorized', 'Not signed in.');
  return { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const headers = await authHeaders();
  const resp = await fetch(`${config.apiUrl}/v1${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!resp.ok) {
    const raw: APIErrorBody = await resp.json().catch(() => ({
      error: { code: 'network_error', message: `HTTP ${resp.status}` },
    }));
    throw new APIError(
      resp.status,
      raw.error.code,
      raw.error.message,
      raw.error.details,
    );
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

export const api = {
  // Twin
  getTwin: () => request<Twin>('GET', '/twin'),
  createTwin: (payload: TwinCreateIn) => request<Twin>('POST', '/twin', payload),
  patchTwin: (payload: TwinProfilePatch) =>
    request<Twin>('PATCH', '/twin', payload),

  // Conversations
  listConversations: () =>
    request<{ items: Conversation[] }>('GET', '/conversations'),
  createConversation: (title?: string) =>
    request<Conversation>('POST', '/conversations', { title }),
  getConversation: (id: UUID) =>
    request<Conversation>('GET', `/conversations/${id}`),
  listMessages: (id: UUID) =>
    request<{ items: Message[] }>('GET', `/conversations/${id}/messages`),
  postMessage: (id: UUID, content: string) =>
    request<MessagePair>('POST', `/conversations/${id}/messages`, { content }),
};

export type API = typeof api;
