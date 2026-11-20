/**
 * Plain-language copy for values the API returns in internal form.
 *
 * The server speaks in enums, scores and audit strings ("PREFERENCE memory
 * learned via confirmed candidate", "conf 0.80", "communication_style_notes").
 * Those are right for logs and wrong for people. Every screen turns them into
 * words through these helpers, so the wording is consistent and testable
 * (jest runs in plain node, so nothing here may import react-native).
 */

import type {
  CommunicationStylePreset,
  EvolutionEventType,
  GoalStatus,
  MemorySourceType,
  ReflectionKind,
} from '@/api/types';

// ---------- time ----------

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** "just now", "5 min ago", "3 h ago", "Yesterday", "Mon", "Nov 3", "Nov 3, 2025". */
export function relativeTime(iso: string, now: Date = new Date()): string {
  const then = new Date(iso);
  const diff = now.getTime() - then.getTime();
  if (Number.isNaN(diff)) return '';
  if (diff < MINUTE) return 'just now';
  if (diff < HOUR) return `${Math.floor(diff / MINUTE)} min ago`;
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  if (then.getTime() >= startOfToday) return `${Math.floor(diff / HOUR)} h ago`;
  if (then.getTime() >= startOfToday - DAY) return 'Yesterday';
  if (then.getTime() >= startOfToday - 6 * DAY) {
    return then.toLocaleDateString('en-US', { weekday: 'short' });
  }
  const sameYear = then.getFullYear() === now.getFullYear();
  return then.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    ...(sameYear ? {} : { year: 'numeric' }),
  });
}

/** "Nov 3, 7:41 PM" — for places that need the exact moment. */
export function shortDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

/** "Nov 3" or "Nov 3, 2025". */
export function shortDate(iso: string, now: Date = new Date()): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    ...(d.getFullYear() === now.getFullYear() ? {} : { year: 'numeric' }),
  });
}

export function greeting(now: Date = new Date()): string {
  const h = now.getHours();
  if (h < 5) return 'Up late';
  if (h < 12) return 'Good morning';
  if (h < 17) return 'Good afternoon';
  return 'Good evening';
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

// ---------- tones (names only; colours live in src/ui/theme.ts) ----------

export type Tone = 'primary' | 'success' | 'warning' | 'info' | 'teal' | 'neutral' | 'danger';

// ---------- memories ----------

export interface Labelled {
  label: string;
  emoji: string;
  tone: Tone;
}

const MEMORY_TYPES: Record<string, Labelled & { plural: string; noun: string }> = {
  FACT: { label: 'Fact', plural: 'Facts', noun: 'fact', emoji: '📌', tone: 'info' },
  PREFERENCE: { label: 'Preference', plural: 'Preferences', noun: 'preference', emoji: '💜', tone: 'primary' },
  EXPERIENCE: { label: 'Experience', plural: 'Experiences', noun: 'experience', emoji: '🌄', tone: 'warning' },
  GOAL: { label: 'Goal', plural: 'Goals', noun: 'goal', emoji: '🎯', tone: 'success' },
};

export function memoryType(type: string): Labelled & { plural: string; noun: string } {
  return (
    MEMORY_TYPES[type] ?? {
      label: 'Memory',
      plural: 'Memories',
      noun: 'memory',
      emoji: '🧠',
      tone: 'neutral',
    }
  );
}

/** How sure the Twin is, in words. Scores are 0..1. */
export function confidenceLabel(score: number): string {
  if (score >= 0.8) return 'Sure about this';
  if (score >= 0.5) return 'Fairly sure';
  return 'A guess';
}

/** How much it matters, in words. Scores are 0..1. */
export function importanceLabel(score: number): string {
  if (score >= 0.7) return 'Important';
  if (score >= 0.4) return 'Worth knowing';
  return 'Minor detail';
}

export function sourceLabel(type: MemorySourceType): string {
  switch (type) {
    case 'message':
      return 'From a chat';
    case 'user_edit':
      return 'Added by you';
    case 'import':
      return 'Imported';
    default:
      return 'Source';
  }
}

// ---------- goals ----------

const GOAL_STATUS: Record<GoalStatus, Labelled> = {
  active: { label: 'Active', emoji: '🟢', tone: 'success' },
  paused: { label: 'Paused', emoji: '⏸️', tone: 'warning' },
  achieved: { label: 'Achieved', emoji: '🎉', tone: 'info' },
  abandoned: { label: 'Dropped', emoji: '🍂', tone: 'neutral' },
};

export function goalStatus(status: GoalStatus): Labelled {
  return GOAL_STATUS[status] ?? { label: status, emoji: '•', tone: 'neutral' };
}

/** The action that moves a goal INTO this status. */
export function goalStatusAction(next: GoalStatus): string {
  switch (next) {
    case 'active':
      return '▶️  Resume';
    case 'paused':
      return '⏸️  Pause';
    case 'achieved':
      return '🎉  Mark achieved';
    case 'abandoned':
      return 'Drop this goal';
  }
}

export const PRIORITIES: ReadonlyArray<{ value: number; label: string }> = [
  { value: 1, label: 'Top' },
  { value: 2, label: 'High' },
  { value: 3, label: 'Medium' },
  { value: 4, label: 'Low' },
  { value: 5, label: 'Someday' },
];

export function priorityLabel(priority: number): string {
  return PRIORITIES.find((p) => p.value === priority)?.label ?? 'Medium';
}

// ---------- communication style ----------

export const STYLES: ReadonlyArray<{
  key: CommunicationStylePreset;
  label: string;
  emoji: string;
  description: string;
}> = [
  { key: 'neutral', label: 'Balanced', emoji: '⚖️', description: 'Clear and even-handed' },
  { key: 'warm', label: 'Warm', emoji: '☀️', description: 'Friendly and encouraging' },
  { key: 'terse', label: 'Brief', emoji: '✂️', description: 'Short and to the point' },
  { key: 'analytical', label: 'Analytical', emoji: '🧭', description: 'Structured and thorough' },
];

export function styleInfo(key: string): { label: string; emoji: string; description: string } {
  return STYLES.find((s) => s.key === key) ?? { label: key, emoji: '💬', description: '' };
}

// ---------- profile fields ----------

export function profileFieldLabel(field: string | null | undefined): string {
  switch (field) {
    case 'communication_style_notes':
      return 'How your Twin talks to you';
    case 'basic_profile':
      return 'The basics about you';
    case 'communication_style_preset':
      return 'Conversation style';
    default:
      return 'Your profile';
  }
}

/** A profile value as people would write it. Objects become "Key: value" lines. */
export function formatProfileValue(value: unknown): string {
  if (value === null || value === undefined) return 'Nothing yet';
  if (typeof value === 'string') return value.trim() ? value : 'Nothing yet';
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) return value.length ? value.map(String).join(', ') : 'Nothing yet';
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>);
    if (!entries.length) return 'Nothing yet';
    return entries.map(([k, v]) => `${humanizeKey(k)}: ${formatProfileValue(v)}`).join('\n');
  }
  return String(value);
}

/** "home_city" -> "Home city". */
export function humanizeKey(key: string): string {
  const spaced = key.replace(/[_-]+/g, ' ').trim();
  return spaced ? spaced.charAt(0).toUpperCase() + spaced.slice(1) : key;
}

// ---------- reflections ----------

export function reflectionKind(kind: ReflectionKind): Labelled {
  switch (kind) {
    case 'profile_update':
      return { label: 'Profile suggestion', emoji: '✏️', tone: 'primary' };
    case 'memory_dedup':
      return { label: 'Duplicate memories', emoji: '🔗', tone: 'info' };
    case 'goal_update':
      return { label: 'Goal note', emoji: '🎯', tone: 'success' };
    case 'insight':
      return { label: 'Insight', emoji: '💡', tone: 'warning' };
  }
}

/** What to tell someone after "Reflect now". */
export function reflectionRunMessage(out: {
  candidates_persisted: number;
  error: string | null;
}): { title: string; body: string } {
  if (out.error) {
    return {
      title: 'Nothing new right now',
      body: "Your Twin couldn't reflect this time. Try again after a few more chats.",
    };
  }
  if (out.candidates_persisted > 0) {
    return {
      title: 'Your Twin has something to share',
      body: `${plural(out.candidates_persisted, 'new thought')} to look at.`,
    };
  }
  return {
    title: 'Nothing new right now',
    body: "Your Twin didn't notice anything it hasn't already mentioned.",
  };
}

// ---------- evolution ----------

export interface FriendlyEvent {
  lead: 'learned' | 'acknowledged';
  /** "Your Twin learned" / "You acknowledged" */
  leadText: string;
  title: string;
  emoji: string;
  tone: Tone;
}

/**
 * A history entry in words. `summary` is the server's audit string; the only
 * thing read from it is the memory type ("PREFERENCE memory learned …") and the
 * profile field ("profile.communication_style_notes updated …") when the event
 * itself does not carry them.
 */
export function friendlyEvent(
  eventType: EvolutionEventType | string,
  summary = '',
  profileField: string | null = null,
): FriendlyEvent {
  const learned = (title: string, emoji: string, tone: Tone): FriendlyEvent => ({
    lead: 'learned',
    leadText: 'Your Twin learned',
    title,
    emoji,
    tone,
  });
  switch (eventType) {
    case 'memory_learned': {
      const m = /^\s*(FACT|PREFERENCE|EXPERIENCE|GOAL)\b/.exec(summary);
      const noun = m ? memoryType(m[1]).noun : null;
      return learned(
        noun ? `A new ${noun} about you` : 'Something new about you',
        m ? memoryType(m[1]).emoji : '🧠',
        'primary',
      );
    }
    case 'memory_consolidated':
      return learned('Two memories were really one', '🔗', 'info');
    case 'goal_updated':
      return learned('A note on one of your goals', '🎯', 'success');
    case 'profile_confirmed': {
      const field = profileField ?? /profile\.(\w+)/.exec(summary)?.[1] ?? null;
      const what =
        field === 'communication_style_notes'
          ? 'How you like it to talk to you'
          : field === 'basic_profile'
            ? 'More of the basics about you'
            : 'An update to your profile';
      return learned(what, '🪞', 'teal');
    }
    case 'insight_acknowledged':
      return {
        lead: 'acknowledged',
        leadText: 'You acknowledged',
        title: 'An insight about you',
        emoji: '💡',
        tone: 'warning',
      };
    default:
      return learned('Something changed', '✨', 'neutral');
  }
}
