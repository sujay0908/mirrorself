/**
 * Pure helpers for mobile UX (Sprint 4). Factored out of components so they
 * are unit-testable without a React Native test renderer.
 */

import type { GoalStatus, Message, UUID } from '@/api/types';

export interface MessageCitations {
  memoryIds: UUID[];
  goalIds: UUID[];
  hasAny: boolean;
}

/** Read the retrieval + goals metadata off a twin message's metadata_json.
 *
 * Returns zero-length arrays for user-role messages and for twin messages
 * that didn't carry metadata (older rows or an unexpected shape).
 */
export function citationsFromMessage(message: Message): MessageCitations {
  if (message.role !== 'twin') {
    return { memoryIds: [], goalIds: [], hasAny: false };
  }
  const meta = message.metadata_json;
  const memoryIds = Array.isArray(meta?.retrieval?.memory_ids)
    ? (meta?.retrieval?.memory_ids as UUID[])
    : [];
  const goalIds = Array.isArray(meta?.goals_context?.goal_ids)
    ? (meta?.goals_context?.goal_ids as UUID[])
    : [];
  return { memoryIds, goalIds, hasAny: memoryIds.length + goalIds.length > 0 };
}

/** Legal next statuses for a goal, mirroring the backend policy.
 *
 * The mobile UI uses this to render only legal transition buttons, so the
 * user cannot submit a request we know will 409.
 */
export const LEGAL_GOAL_TRANSITIONS: Record<GoalStatus, GoalStatus[]> = {
  active: ['achieved', 'abandoned', 'paused'],
  paused: ['active', 'achieved', 'abandoned'],
  achieved: [],
  abandoned: [],
};

export function legalNextStates(from: GoalStatus): GoalStatus[] {
  return LEGAL_GOAL_TRANSITIONS[from];
}
