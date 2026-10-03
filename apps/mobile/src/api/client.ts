/**
 * Thin fetch wrapper. Attaches the current Supabase JWT to every request,
 * unwraps the error envelope, and returns typed bodies.
 */

import { supabase } from '@/auth/supabase';
import { config } from '@/config';
import type {
  APIErrorBody,
  Conversation,
  Goal,
  GoalCreateIn,
  GoalEvent,
  GoalStatus,
  GoalUpdateIn,
  Memory,
  MemoryCandidate,
  MemoryCandidateConfirm,
  MemoryPatch,
  MemoryProvenance,
  MemoryType,
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

export type CandidateQuery =
  | 'pending'
  | 'confirmed'
  | 'rejected'
  | 'expired'
  | 'all';

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

  // Memories (Sprint 4)
  listMemories: (type?: MemoryType) => {
    const q = type ? `?type=${encodeURIComponent(type)}` : '';
    return request<{ items: Memory[] }>('GET', `/memories${q}`);
  },
  getMemory: (id: UUID) => request<Memory>('GET', `/memories/${id}`),
  patchMemory: (id: UUID, patch: MemoryPatch) =>
    request<Memory>('PATCH', `/memories/${id}`, patch),
  deleteMemory: (id: UUID) => request<void>('DELETE', `/memories/${id}`),
  getMemoryProvenance: (id: UUID) =>
    request<MemoryProvenance>('GET', `/memories/${id}/provenance`),

  // Memory candidates (Sprint 2 + reuse in Sprint 4 UX)
  listCandidates: (status: CandidateQuery = 'pending') => {
    const q = status === 'all' ? '?status=all' : `?status=${status}`;
    return request<{ items: MemoryCandidate[] }>(
      'GET',
      `/memory-candidates${q}`,
    );
  },
  confirmCandidate: (id: UUID) =>
    request<MemoryCandidateConfirm>(
      'POST',
      `/memory-candidates/${id}/confirm`,
    ),
  rejectCandidate: (id: UUID) =>
    request<MemoryCandidate>('POST', `/memory-candidates/${id}/reject`),

  // Goals (Sprint 4)
  listGoals: (status?: GoalStatus) => {
    const q = status ? `?status=${status}` : '';
    return request<{ items: Goal[] }>('GET', `/goals${q}`);
  },
  createGoal: (payload: GoalCreateIn) =>
    request<Goal>('POST', '/goals', payload),
  getGoal: (id: UUID) => request<Goal>('GET', `/goals/${id}`),
  patchGoal: (id: UUID, patch: GoalUpdateIn) =>
    request<Goal>('PATCH', `/goals/${id}`, patch),
  listGoalEvents: (id: UUID) =>
    request<{ items: GoalEvent[] }>('GET', `/goals/${id}/events`),
};

export type API = typeof api;
