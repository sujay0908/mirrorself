/**
 * Pure-function tests for the Sprint 10 mobile learning helper, which
 * drives the tap-to-reveal "Your Twin learned…" chip under a twin reply.
 */

import type { LearningMeta, Message } from '@/api/types';
import { learningFromMessage, learningHeadline } from '@/lib/learning';

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
    created_at: '2026-10-10T00:00:00Z',
  };
}

const learned: LearningMeta = {
  count: 1,
  acknowledged_up_to_seq: 7,
  has_learned: true,
  has_acknowledged: false,
  items: [
    {
      id: 'a1',
      event_type: 'memory_learned',
      lead: 'learned',
      summary: 'FACT memory learned via confirmed candidate',
      seq: 7,
    },
  ],
};

describe('learningFromMessage', () => {
  test('user messages never produce a learning block', () => {
    const m: Message = { ...twinMessage({ learning: learned }), role: 'user' };
    expect(learningFromMessage(m).hasAny).toBe(false);
  });

  test('twin message with no metadata produces nothing', () => {
    expect(learningFromMessage(twinMessage()).hasAny).toBe(false);
  });

  test('explicit null learning produces nothing', () => {
    expect(learningFromMessage(twinMessage({ learning: null })).hasAny).toBe(false);
  });

  test('a learned event surfaces with hasLearned', () => {
    const r = learningFromMessage(twinMessage({ learning: learned }));
    expect(r.hasAny).toBe(true);
    expect(r.count).toBe(1);
    expect(r.hasLearned).toBe(true);
    expect(r.hasAcknowledged).toBe(false);
    expect(r.items[0].summary).toContain('memory learned');
  });

  test('acknowledged vs learned leads are distinguished', () => {
    const meta: LearningMeta = {
      count: 2,
      acknowledged_up_to_seq: 9,
      has_learned: true,
      has_acknowledged: true,
      items: [
        { id: 'a', event_type: 'memory_learned', lead: 'learned', summary: 'm', seq: 8 },
        {
          id: 'b',
          event_type: 'insight_acknowledged',
          lead: 'acknowledged',
          summary: 'i',
          seq: 9,
        },
      ],
    };
    const r = learningFromMessage(twinMessage({ learning: meta }));
    expect(r.hasLearned).toBe(true);
    expect(r.hasAcknowledged).toBe(true);
    expect(r.count).toBe(2);
  });

  test('malformed items are filtered (no crash)', () => {
    const r = learningFromMessage(
      twinMessage({
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        learning: { items: [{ nope: true }, 'garbage'] } as any,
      }),
    );
    expect(r.hasAny).toBe(false);
  });

  test('non-object learning is tolerated', () => {
    const r = learningFromMessage(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      twinMessage({ learning: 'not-an-object' as any }),
    );
    expect(r.hasAny).toBe(false);
  });
});

describe('learningHeadline', () => {
  test('single learned', () => {
    expect(learningHeadline(learningFromMessage(twinMessage({ learning: learned })))).toBe(
      'Your Twin learned something',
    );
  });

  test('acknowledged-only phrasing', () => {
    const meta: LearningMeta = {
      count: 1,
      acknowledged_up_to_seq: 3,
      has_learned: false,
      has_acknowledged: true,
      items: [
        { id: 'x', event_type: 'insight_acknowledged', lead: 'acknowledged', summary: 'i', seq: 3 },
      ],
    };
    expect(learningHeadline(learningFromMessage(twinMessage({ learning: meta })))).toBe(
      'You acknowledged an insight',
    );
  });
});
