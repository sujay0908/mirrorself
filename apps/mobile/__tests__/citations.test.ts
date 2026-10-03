/**
 * Pure-function tests for the Sprint 4 mobile helpers:
 *  - citationsFromMessage: drives the tap-to-reveal "Memories used" UI
 *  - legalNextStates: drives the goal detail status buttons
 */

import type { Message } from '@/api/types';
import { citationsFromMessage, legalNextStates } from '@/lib/citations';

function twinMessage(meta?: Message['metadata_json']): Message {
  return {
    id: '00000000-0000-0000-0000-000000000000',
    conversation_id: '00000000-0000-0000-0000-000000000000',
    role: 'twin',
    content: 'hi',
    llm_provider: 'mock',
    llm_model: 'mock-echo',
    input_tokens: 1,
    output_tokens: 1,
    metadata_json: meta,
    created_at: '2026-10-03T00:00:00Z',
  };
}

describe('citationsFromMessage', () => {
  test('user messages never produce citations', () => {
    const m: Message = { ...twinMessage(), role: 'user' };
    expect(citationsFromMessage(m)).toEqual({
      memoryIds: [],
      goalIds: [],
      hasAny: false,
    });
  });

  test('twin message with no metadata_json produces no citations', () => {
    expect(citationsFromMessage(twinMessage())).toEqual({
      memoryIds: [],
      goalIds: [],
      hasAny: false,
    });
  });

  test('twin message exposes memory ids from retrieval', () => {
    const r = citationsFromMessage(
      twinMessage({
        retrieval: {
          ok: true,
          error: null,
          memories_returned: 2,
          memory_ids: ['a', 'b'],
        },
      }),
    );
    expect(r.memoryIds).toEqual(['a', 'b']);
    expect(r.goalIds).toEqual([]);
    expect(r.hasAny).toBe(true);
  });

  test('twin message exposes goal ids from goals_context', () => {
    const r = citationsFromMessage(
      twinMessage({
        goals_context: {
          ok: true,
          error: null,
          goals_used: 1,
          goal_ids: ['g1'],
        },
      }),
    );
    expect(r.goalIds).toEqual(['g1']);
    expect(r.memoryIds).toEqual([]);
    expect(r.hasAny).toBe(true);
  });

  test('both memories and goals surface together', () => {
    const r = citationsFromMessage(
      twinMessage({
        retrieval: {
          ok: true,
          error: null,
          memories_returned: 1,
          memory_ids: ['m1'],
        },
        goals_context: {
          ok: true,
          error: null,
          goals_used: 1,
          goal_ids: ['g1'],
        },
      }),
    );
    expect(r.memoryIds).toEqual(['m1']);
    expect(r.goalIds).toEqual(['g1']);
    expect(r.hasAny).toBe(true);
  });

  test('malformed metadata is tolerated (no crash)', () => {
    const r = citationsFromMessage(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      twinMessage({ retrieval: 'not-an-object' as any }),
    );
    expect(r.memoryIds).toEqual([]);
    expect(r.goalIds).toEqual([]);
    expect(r.hasAny).toBe(false);
  });
});

describe('legalNextStates', () => {
  test('active can go to achieved, abandoned, paused', () => {
    expect(legalNextStates('active').sort()).toEqual([
      'abandoned',
      'achieved',
      'paused',
    ]);
  });

  test('paused can go to active, achieved, abandoned', () => {
    expect(legalNextStates('paused').sort()).toEqual([
      'abandoned',
      'achieved',
      'active',
    ]);
  });

  test('achieved and abandoned are terminal', () => {
    expect(legalNextStates('achieved')).toEqual([]);
    expect(legalNextStates('abandoned')).toEqual([]);
  });
});
