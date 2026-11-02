/**
 * Loading state for the home screen's conversation list.
 *
 * Extracted from the screen so the failure path is testable: jest runs in a
 * node environment with no React Native transform, which is why the auth gate
 * lives in src/auth/route-guard.ts rather than in the component too.
 *
 * The distinction this type exists to enforce: a fetch that SUCCEEDED and
 * returned nothing, and a fetch that FAILED, are different states. Collapsing
 * them is what let a dead backend render "No conversations yet" — the screen
 * used `.then(...).finally(...)` with no rejection handler, so a rejection
 * escaped as an unhandled promise rejection while `loading` was still cleared
 * and the list stayed empty.
 */

import type { ApiFailure } from '@/api/diagnostics';
import type { Conversation } from '@/api/types';

export type ConversationListState =
  | { status: 'loading' }
  | { status: 'ready'; items: Conversation[] }
  | { status: 'failed'; failure: ApiFailure };

export type ConversationListEvent =
  /** Initial load, and the retry action — they are the same transition. */
  | { type: 'load' }
  | { type: 'loaded'; items: Conversation[] }
  | { type: 'failed'; failure: ApiFailure };

export const CONVERSATIONS_INITIAL: ConversationListState = { status: 'loading' };

export function conversationListReducer(
  state: ConversationListState,
  event: ConversationListEvent,
): ConversationListState {
  switch (event.type) {
    case 'load':
      // Reachable from every state: the first fetch and a retry after a
      // failure are the same transition, so retry cannot be forgotten.
      return { status: 'loading' };
    case 'loaded':
      return { status: 'ready', items: event.items };
    case 'failed':
      return { status: 'failed', failure: event.failure };
    default:
      return state;
  }
}

/**
 * Whether to render the "no conversations yet" copy.
 *
 * Only ever true for a request that succeeded. A failure must never be
 * presented as an empty account.
 */
export function showsEmptyState(state: ConversationListState): boolean {
  return state.status === 'ready' && state.items.length === 0;
}
