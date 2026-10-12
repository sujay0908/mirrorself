/**
 * Pure helper for the Sprint 10 chat-time learning acknowledgement.
 *
 * Reads the `learning` block the backend writes into a twin message's
 * metadata_json and normalizes it into a shape the MessageBubble can
 * render without defensive checks. Factored out of the component so it
 * is unit-testable without a React Native renderer (mirrors
 * `citationsFromMessage`).
 */

import type { LearningItem, Message } from '@/api/types';

export interface MessageLearning {
  items: LearningItem[];
  count: number;
  hasAny: boolean;
  /** At least one durable change ("Your Twin learned…"). */
  hasLearned: boolean;
  /** At least one insight acknowledgement ("You acknowledged…"). */
  hasAcknowledged: boolean;
}

const EMPTY: MessageLearning = {
  items: [],
  count: 0,
  hasAny: false,
  hasLearned: false,
  hasAcknowledged: false,
};

function isLearningItem(x: unknown): x is LearningItem {
  if (typeof x !== 'object' || x === null) {
    return false;
  }
  const o = x as Record<string, unknown>;
  return (
    typeof o.id === 'string' &&
    typeof o.event_type === 'string' &&
    (o.lead === 'learned' || o.lead === 'acknowledged') &&
    typeof o.summary === 'string' &&
    typeof o.seq === 'number'
  );
}

/**
 * Read the learning acknowledgement off a twin message's metadata_json.
 *
 * Returns an empty result for user-role messages, for twin messages that
 * carried no learning block (the common case), and for any malformed or
 * unexpected shape — so the caller never crashes on old rows or partial
 * data.
 */
export function learningFromMessage(message: Message): MessageLearning {
  if (message.role !== 'twin') {
    return EMPTY;
  }
  const raw = message.metadata_json?.learning;
  if (raw === null || raw === undefined || typeof raw !== 'object') {
    return EMPTY;
  }
  const items = Array.isArray(raw.items) ? raw.items.filter(isLearningItem) : [];
  if (items.length === 0) {
    return EMPTY;
  }
  return {
    items,
    count: items.length,
    hasAny: true,
    hasLearned: items.some((it) => it.lead === 'learned'),
    hasAcknowledged: items.some((it) => it.lead === 'acknowledged'),
  };
}

/** One-line header for the chip, chosen by what the slice contains. */
export function learningHeadline(learning: MessageLearning): string {
  const n = learning.count;
  const noun = n === 1 ? 'update' : 'updates';
  if (learning.hasLearned && learning.hasAcknowledged) {
    return `Your Twin evolved · ${n} ${noun}`;
  }
  if (learning.hasLearned) {
    return n === 1 ? 'Your Twin learned something' : `Your Twin learned ${n} things`;
  }
  return n === 1 ? 'You acknowledged an insight' : `You acknowledged ${n} insights`;
}
