/**
 * Type-level smoke test — the shape of the API types stays in sync with the
 * backend Pydantic schemas. This is a compile-time check.
 *
 * We import types ONLY from `@/api/types` (and the API shape type from
 * `@/api/client`). We do not import the runtime `api` object or
 * `@/auth/supabase`, which would require a Supabase/Expo test harness that
 * this smoke test does not need.
 */

import type {
  Goal,
  GoalEvent,
  GoalStatus,
  Memory,
  MemoryCandidate,
  MemoryProvenance,
  Message,
  Twin,
} from '@/api/types';
import type { API } from '@/api/client';

// If these compile, the types stayed compatible.
const _twinSample: Twin = {
  id: '00000000-0000-0000-0000-000000000000',
  user_id: '00000000-0000-0000-0000-000000000000',
  display_name: 'Aurora',
  profile: {
    id: '00000000-0000-0000-0000-000000000000',
    twin_id: '00000000-0000-0000-0000-000000000000',
    communication_style_preset: 'warm',
    communication_style_notes: null,
    basic_profile: {},
    created_at: '2026-09-25T00:00:00Z',
    updated_at: '2026-09-25T00:00:00Z',
  },
  created_at: '2026-09-25T00:00:00Z',
  updated_at: '2026-09-25T00:00:00Z',
};

const _messageSample: Message = {
  id: '00000000-0000-0000-0000-000000000000',
  conversation_id: '00000000-0000-0000-0000-000000000000',
  role: 'twin',
  content: 'hello',
  llm_provider: 'mock',
  llm_model: 'mock-echo',
  input_tokens: 1,
  output_tokens: 1,
  metadata_json: {
    retrieval: {
      ok: true,
      error: null,
      memories_returned: 1,
      memory_ids: ['00000000-0000-0000-0000-000000000000'],
    },
    goals_context: {
      ok: true,
      error: null,
      goals_used: 1,
      goal_ids: ['00000000-0000-0000-0000-000000000000'],
    },
  },
  created_at: '2026-09-25T00:00:00Z',
};

const _goalSample: Goal = {
  id: '00000000-0000-0000-0000-000000000000',
  twin_id: '00000000-0000-0000-0000-000000000000',
  title: 'Ship Sprint 4',
  description: null,
  target_date: null,
  priority: 2,
  status: 'active',
  status_changed_at: '2026-10-03T00:00:00Z',
  created_at: '2026-10-03T00:00:00Z',
  updated_at: '2026-10-03T00:00:00Z',
};

const _goalEventSample: GoalEvent = {
  id: '00000000-0000-0000-0000-000000000000',
  goal_id: '00000000-0000-0000-0000-000000000000',
  event_type: 'status_changed',
  from_status: 'active',
  to_status: 'achieved',
  note: 'done',
  created_at: '2026-10-03T00:00:00Z',
};

const _candidateSample: MemoryCandidate = {
  id: '00000000-0000-0000-0000-000000000000',
  user_id: '00000000-0000-0000-0000-000000000000',
  twin_id: '00000000-0000-0000-0000-000000000000',
  type: 'PREFERENCE',
  content: 'prefers concise answers',
  confidence: 0.8,
  importance: 0.6,
  source_message_id: null,
  source_conversation_id: null,
  status: 'pending',
  resulting_memory_id: null,
  created_at: '2026-10-03T00:00:00Z',
  updated_at: '2026-10-03T00:00:00Z',
};

const _memorySample: Memory = {
  id: '00000000-0000-0000-0000-000000000000',
  user_id: '00000000-0000-0000-0000-000000000000',
  twin_id: '00000000-0000-0000-0000-000000000000',
  type: 'FACT',
  content: 'lives in Bengaluru',
  source: 'candidate_confirmation',
  confidence: 0.9,
  importance: 0.8,
  user_confirmed: true,
  last_confirmed_at: '2026-10-03T00:00:00Z',
  metadata_json: {},
  created_at: '2026-10-03T00:00:00Z',
  updated_at: '2026-10-03T00:00:00Z',
  sources: [],
};

const _provSample: MemoryProvenance = {
  memory_id: '00000000-0000-0000-0000-000000000000',
  sources: [
    {
      source_id: '00000000-0000-0000-0000-000000000000',
      source_type: 'message',
      source_message_id: '00000000-0000-0000-0000-000000000000',
      source_conversation_id: '00000000-0000-0000-0000-000000000000',
      created_at: '2026-10-03T00:00:00Z',
      source_snippet: 'I live in Bengaluru.',
      source_snippet_truncated: false,
    },
  ],
};

// Compile-time assertion that Sprint 4 methods exist on the API shape.
type _ApiHas = Pick<
  API,
  | 'listGoals'
  | 'createGoal'
  | 'getGoal'
  | 'patchGoal'
  | 'listGoalEvents'
  | 'listMemories'
  | 'getMemory'
  | 'patchMemory'
  | 'deleteMemory'
  | 'getMemoryProvenance'
  | 'listCandidates'
  | 'confirmCandidate'
  | 'rejectCandidate'
>;

// If this reference compiles, every method above is present on `API`.
const _apiShape: null | _ApiHas = null;

test('type smoke passes', () => {
  expect(_twinSample.display_name).toBe('Aurora');
  expect(_messageSample.role).toBe('twin');
  expect(_messageSample.metadata_json?.retrieval?.ok).toBe(true);
  const activeStatus: GoalStatus = _goalSample.status;
  expect(activeStatus).toBe('active');
  expect(_goalEventSample.event_type).toBe('status_changed');
  expect(_candidateSample.status).toBe('pending');
  expect(_memorySample.user_confirmed).toBe(true);
  expect(_provSample.sources[0].source_snippet).toBe('I live in Bengaluru.');
  expect(_apiShape).toBeNull();
});
