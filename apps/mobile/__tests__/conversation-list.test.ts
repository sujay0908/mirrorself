/**
 * Regression tests for the home screen's silently-empty conversation list.
 *
 * The screen ran:
 *
 *   api.listConversations().then(setItems).finally(() => setLoading(false))
 *
 * `.finally()` does not handle a rejection, it re-throws it. So a failed
 * fetch escaped as "Uncaught (in promise)" — observed in production on a
 * deep link to /home while signed out — while `loading` was cleared and the
 * list stayed empty. A dead backend was therefore indistinguishable from an
 * account with no conversations.
 *
 * These pin both halves of the fix: every failure reaches a terminal state
 * that is NOT an empty list, and that state is recoverable by retrying.
 */

import { describeApiFailure, apiFailureMessage } from '@/api/diagnostics';
import { APIError } from '@/api/errors';
import {
  CONVERSATIONS_INITIAL,
  conversationListReducer,
  showsEmptyState,
  type ConversationListState,
} from '@/state/conversation-list';
import type { Conversation } from '@/api/types';

const API_URL = 'https://api.timeismetime.com';

const conversation = (id: string): Conversation => ({
  id,
  twin_id: 'twin-1',
  title: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
});

const failureFrom = (err: unknown) => ({
  type: 'failed' as const,
  failure: describeApiFailure(err),
});

describe('conversation list - a failure is never an empty account', () => {
  it('starts in loading, not in an empty ready state', () => {
    expect(CONVERSATIONS_INITIAL).toEqual({ status: 'loading' });
    expect(showsEmptyState(CONVERSATIONS_INITIAL)).toBe(false);
  });

  it('turns an unreachable backend into a failure, not an empty list', () => {
    // A rejected fetch (connection refused / DNS / CORS) arrives as TypeError.
    const next = conversationListReducer(
      CONVERSATIONS_INITIAL,
      failureFrom(new TypeError('Failed to fetch')),
    );
    expect(next.status).toBe('failed');
    expect(showsEmptyState(next)).toBe(false);
  });

  it('turns a rejected session into a failure, not an empty list', () => {
    // This is the exact error seen in production: client.ts throws it when
    // there is no access token.
    const next = conversationListReducer(
      CONVERSATIONS_INITIAL,
      failureFrom(new APIError(401, 'unauthorized', 'Not signed in.')),
    );
    expect(next.status).toBe('failed');
    if (next.status === 'failed') {
      expect(next.failure.kind).toBe('unauthorized');
    }
    expect(showsEmptyState(next)).toBe(false);
  });

  it('still reports a genuinely empty account as empty', () => {
    const next = conversationListReducer(CONVERSATIONS_INITIAL, {
      type: 'loaded',
      items: [],
    });
    expect(next).toEqual({ status: 'ready', items: [] });
    expect(showsEmptyState(next)).toBe(true);
  });

  it('reports a populated account as ready and not empty', () => {
    const next = conversationListReducer(CONVERSATIONS_INITIAL, {
      type: 'loaded',
      items: [conversation('c1'), conversation('c2')],
    });
    expect(next.status).toBe('ready');
    if (next.status === 'ready') expect(next.items).toHaveLength(2);
    expect(showsEmptyState(next)).toBe(false);
  });
});

describe('conversation list - retry', () => {
  const failed: ConversationListState = conversationListReducer(
    CONVERSATIONS_INITIAL,
    failureFrom(new TypeError('Failed to fetch')),
  );

  it('returns to loading from a failure, so the error is recoverable', () => {
    expect(conversationListReducer(failed, { type: 'load' })).toEqual({
      status: 'loading',
    });
  });

  it('returns to loading from a ready list, so a refresh works too', () => {
    const ready = conversationListReducer(CONVERSATIONS_INITIAL, {
      type: 'loaded',
      items: [conversation('c1')],
    });
    expect(conversationListReducer(ready, { type: 'load' })).toEqual({
      status: 'loading',
    });
  });

  it('recovers fully when the retry succeeds', () => {
    const loading = conversationListReducer(failed, { type: 'load' });
    const recovered = conversationListReducer(loading, {
      type: 'loaded',
      items: [conversation('c1')],
    });
    expect(recovered.status).toBe('ready');
    expect(showsEmptyState(recovered)).toBe(false);
  });

  it('a retry that fails again stays failed rather than falling back to empty', () => {
    const loading = conversationListReducer(failed, { type: 'load' });
    const again = conversationListReducer(
      loading,
      failureFrom(new APIError(500, 'server_error', 'boom')),
    );
    expect(again.status).toBe('failed');
    if (again.status === 'failed') expect(again.failure.status).toBe(500);
    expect(showsEmptyState(again)).toBe(false);
  });
});

describe('conversation list - what the user is told', () => {
  it('names the API origin when the backend cannot be reached', () => {
    const failure = describeApiFailure(new TypeError('Failed to fetch'));
    expect(apiFailureMessage(failure, API_URL)).toContain(API_URL);
  });

  it('explains a rejected session rather than showing an empty list', () => {
    const failure = describeApiFailure(
      new APIError(401, 'unauthorized', 'Not signed in.'),
    );
    const message = apiFailureMessage(failure, API_URL);
    expect(message).toContain('401');
    // Server-supplied text may echo user input and is never rendered.
    expect(message).not.toContain('Not signed in.');
  });

  it('explains a server error with its status', () => {
    const failure = describeApiFailure(new APIError(503, 'server_error', 'x'));
    expect(apiFailureMessage(failure, API_URL)).toContain('503');
  });
});
