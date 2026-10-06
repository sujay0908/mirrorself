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
  EvolutionEvent,
  EvolutionListOut,
  Goal,
  GoalEvent,
  GoalStatus,
  Memory,
  MemoryCandidate,
  MemoryProvenance,
  Message,
  Reflection,
  ReflectionConfirmOut,
  ReflectionRunOut,
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
  superseded_by_memory_id: null,
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
  // Sprint 7 reflection surface
  | 'listReflections'
  | 'runReflections'
  | 'confirmReflection'
  | 'rejectReflection'
  | 'unsupersedeMemory'
  // Sprint 8 evolution surface
  | 'listEvolution'
>;

// If this reference compiles, every method above is present on `API`.
const _apiShape: null | _ApiHas = null;

// Sprint 7: a profile_update reflection sample. The payload is a
// discriminated union; this literal pins the discriminator so the
// compiler verifies the per-kind field set.
const _reflectionSample: Reflection = {
  id: '00000000-0000-0000-0000-000000000000',
  user_id: '00000000-0000-0000-0000-000000000000',
  twin_id: '00000000-0000-0000-0000-000000000000',
  kind: 'profile_update',
  status: 'pending',
  proposed_payload: {
    kind: 'profile_update',
    field: 'communication_style_notes',
    current_value: null,
    proposed_value: 'Prefers short answers in the morning.',
    rationale: 'Observed over three morning sessions.',
  },
  source_memory_ids: ['00000000-0000-0000-0000-000000000000'],
  source_goal_ids: [],
  rationale: 'Observed over three morning sessions.',
  confidence: 0.7,
  importance: 0.5,
  resolved_at: null,
  apply_error: null,
  apply_metadata: {},
  created_at: '2026-10-05T00:00:00Z',
  updated_at: '2026-10-05T00:00:00Z',
};

const _confirmOutSample: ReflectionConfirmOut = {
  reflection: { ..._reflectionSample, status: 'confirmed' },
  applied: true,
  apply_metadata: { kind: 'profile_update' },
};

const _runOutSample: ReflectionRunOut = {
  candidates_proposed: 2,
  candidates_persisted: 2,
  candidates_deduplicated: 0,
  error: null,
};

// Sprint 8: evolution event samples. profile_confirmed (identity
// mutation, "learned") and insight_acknowledged (acknowledgement,
// not identity mutation — rendered as "You acknowledged...").
const _evolutionProfileSample: EvolutionEvent = {
  id: '00000000-0000-0000-0000-000000000000',
  user_id: '00000000-0000-0000-0000-000000000000',
  twin_id: '00000000-0000-0000-0000-000000000000',
  event_type: 'profile_confirmed',
  reflection_id: '00000000-0000-0000-0000-000000000001',
  memory_id: null,
  goal_id: null,
  profile_field: 'communication_style_notes',
  summary: 'profile.communication_style_notes updated via confirmed reflection',
  created_at: '2026-10-06T00:00:00Z',
};

const _evolutionInsightSample: EvolutionEvent = {
  id: '00000000-0000-0000-0000-000000000002',
  user_id: '00000000-0000-0000-0000-000000000000',
  twin_id: '00000000-0000-0000-0000-000000000000',
  event_type: 'insight_acknowledged',
  reflection_id: '00000000-0000-0000-0000-000000000003',
  memory_id: null,
  goal_id: null,
  profile_field: null,
  summary: 'insight acknowledged (no memory or profile change)',
  created_at: '2026-10-06T00:00:00Z',
};

const _evolutionListSample: EvolutionListOut = {
  items: [_evolutionProfileSample, _evolutionInsightSample],
};

test('type smoke passes', () => {
  expect(_twinSample.display_name).toBe('Aurora');
  expect(_messageSample.role).toBe('twin');
  expect(_messageSample.metadata_json?.retrieval?.ok).toBe(true);
  const activeStatus: GoalStatus = _goalSample.status;
  expect(activeStatus).toBe('active');
  expect(_goalEventSample.event_type).toBe('status_changed');
  expect(_candidateSample.status).toBe('pending');
  expect(_memorySample.user_confirmed).toBe(true);
  expect(_memorySample.superseded_by_memory_id).toBeNull();
  expect(_provSample.sources[0].source_snippet).toBe('I live in Bengaluru.');
  expect(_apiShape).toBeNull();
  expect(_reflectionSample.kind).toBe('profile_update');
  if (_reflectionSample.proposed_payload.kind === 'profile_update') {
    expect(_reflectionSample.proposed_payload.field).toBe(
      'communication_style_notes',
    );
  }
  expect(_confirmOutSample.applied).toBe(true);
  expect(_runOutSample.candidates_proposed).toBe(2);
  // Sprint 8: profile_confirmed → "learned"; insight_acknowledged
  // → the distinct non-identity-mutation event. Both are present on
  // the discriminated union.
  expect(_evolutionProfileSample.event_type).toBe('profile_confirmed');
  expect(_evolutionInsightSample.event_type).toBe('insight_acknowledged');
  expect(_evolutionListSample.items).toHaveLength(2);
});
