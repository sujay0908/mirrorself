/**
 * API types. Hand-authored for Sprint 1; regenerated from OpenAPI in a later
 * sprint (see packages/shared-types/README.md).
 */

export type UUID = string;
export type ISODateTime = string;

export type CommunicationStylePreset =
  | 'neutral'
  | 'terse'
  | 'warm'
  | 'analytical';

export type MessageRole = 'user' | 'twin' | 'system';

export type MemoryType = 'FACT' | 'PREFERENCE' | 'EXPERIENCE' | 'GOAL';
export type MemorySourceType = 'message' | 'user_edit' | 'import';
export type CandidateStatus = 'pending' | 'confirmed' | 'rejected' | 'expired';
export type GoalStatus = 'active' | 'achieved' | 'abandoned' | 'paused';
export type GoalEventType = 'created' | 'updated' | 'status_changed';

export interface TwinProfile {
  id: UUID;
  twin_id: UUID;
  communication_style_preset: CommunicationStylePreset;
  communication_style_notes: string | null;
  basic_profile: Record<string, unknown>;
  created_at: ISODateTime;
  updated_at: ISODateTime;
}

export interface Twin {
  id: UUID;
  user_id: UUID;
  display_name: string;
  profile: TwinProfile;
  created_at: ISODateTime;
  updated_at: ISODateTime;
}

export interface TwinCreateIn {
  name: string;
  communication_style?: CommunicationStylePreset;
  basic_profile?: Record<string, unknown>;
}

export interface TwinProfilePatch {
  display_name?: string;
  communication_style_preset?: CommunicationStylePreset;
  communication_style_notes?: string | null;
  basic_profile?: Record<string, unknown>;
}

export interface Conversation {
  id: UUID;
  twin_id: UUID;
  title: string | null;
  created_at: ISODateTime;
  updated_at: ISODateTime;
}

/** Sprint 4: metadata the twin message carries from `ConversationService`. */
export interface RetrievalMeta {
  ok: boolean;
  error: string | null;
  memories_returned: number;
  memory_ids: UUID[];
}

export interface GoalsContextMeta {
  ok: boolean;
  error: string | null;
  goals_used: number;
  goal_ids: UUID[];
}

export interface MessageMetadata {
  finish_reason?: string | null;
  retrieval?: RetrievalMeta;
  goals_context?: GoalsContextMeta;
  [key: string]: unknown;
}

export interface Message {
  id: UUID;
  conversation_id: UUID;
  role: MessageRole;
  content: string;
  llm_provider: string | null;
  llm_model: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  metadata_json?: MessageMetadata;
  created_at: ISODateTime;
}

export interface MessagePair {
  user_message: Message;
  twin_message: Message;
}

export interface APIErrorBody {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
    request_id?: string;
  };
}

// ---------- Memory (Sprint 2 + 4) ----------

export interface MemorySource {
  id: UUID;
  source_type: MemorySourceType;
  source_message_id: UUID | null;
  source_conversation_id: UUID | null;
  source_metadata: Record<string, unknown>;
  created_at: ISODateTime;
}

export interface Memory {
  id: UUID;
  user_id: UUID;
  twin_id: UUID;
  type: MemoryType;
  content: string;
  source: string;
  confidence: number;
  importance: number;
  user_confirmed: boolean;
  last_confirmed_at: ISODateTime | null;
  /**
   * Sprint 7: non-null when this memory has been superseded by a
   * confirmed `memory_dedup` reflection. The row is NOT deleted; the
   * memory list still exposes it, but context-building retrieval
   * excludes it. See docs/architecture/reflection.md.
   */
  superseded_by_memory_id: UUID | null;
  metadata_json: Record<string, unknown>;
  created_at: ISODateTime;
  updated_at: ISODateTime;
  sources: MemorySource[];
}

export interface MemoryPatch {
  content?: string;
  importance?: number;
  metadata?: Record<string, unknown>;
}

export interface MemoryCandidate {
  id: UUID;
  user_id: UUID;
  twin_id: UUID;
  type: MemoryType;
  content: string;
  confidence: number;
  importance: number;
  source_message_id: UUID | null;
  source_conversation_id: UUID | null;
  status: CandidateStatus;
  resulting_memory_id: UUID | null;
  created_at: ISODateTime;
  updated_at: ISODateTime;
}

export interface MemoryCandidateConfirm {
  candidate: MemoryCandidate;
  memory: Memory;
  embedding_attached: boolean;
  embedding_error: string | null;
}

export interface MemoryProvenanceSource {
  source_id: UUID;
  source_type: MemorySourceType;
  source_message_id: UUID | null;
  source_conversation_id: UUID | null;
  created_at: ISODateTime;
  source_snippet: string | null;
  source_snippet_truncated: boolean;
}

export interface MemoryProvenance {
  memory_id: UUID;
  sources: MemoryProvenanceSource[];
}

// ---------- Goals (Sprint 4) ----------

export interface Goal {
  id: UUID;
  twin_id: UUID;
  title: string;
  description: string | null;
  target_date: ISODateTime | null;
  priority: number;
  status: GoalStatus;
  status_changed_at: ISODateTime;
  created_at: ISODateTime;
  updated_at: ISODateTime;
}

export interface GoalCreateIn {
  title: string;
  description?: string | null;
  target_date?: ISODateTime | null;
  priority?: number;
}

export interface GoalUpdateIn {
  title?: string;
  description?: string | null;
  target_date?: ISODateTime | null;
  priority?: number;
  status?: GoalStatus;
  status_note?: string;
}

export interface GoalEvent {
  id: UUID;
  goal_id: UUID;
  event_type: GoalEventType;
  from_status: GoalStatus | null;
  to_status: GoalStatus | null;
  note: string | null;
  created_at: ISODateTime;
}

// ---------- Reflections (Sprint 7) ----------

export type ReflectionKind =
  | 'profile_update'
  | 'memory_dedup'
  | 'goal_update'
  | 'insight';

export type ReflectionStatus = 'pending' | 'confirmed' | 'rejected';

export type ProfileUpdateField =
  | 'communication_style_notes'
  | 'basic_profile';

export interface ProfileUpdatePayload {
  kind: 'profile_update';
  field: ProfileUpdateField;
  current_value: unknown;
  proposed_value: unknown;
  rationale: string;
}

export interface MemoryDedupPayload {
  kind: 'memory_dedup';
  superseded_memory_id: UUID;
  canonical_memory_id: UUID;
  rationale: string;
}

export interface GoalUpdatePayload {
  kind: 'goal_update';
  goal_id: UUID;
  note: string;
  rationale: string;
}

export interface InsightPayload {
  kind: 'insight';
  headline: string;
  body: string;
  rationale: string;
}

export type ReflectionPayload =
  | ProfileUpdatePayload
  | MemoryDedupPayload
  | GoalUpdatePayload
  | InsightPayload;

export interface Reflection {
  id: UUID;
  user_id: UUID;
  twin_id: UUID;
  kind: ReflectionKind;
  status: ReflectionStatus;
  proposed_payload: ReflectionPayload;
  source_memory_ids: UUID[];
  source_goal_ids: UUID[];
  rationale: string | null;
  confidence: number;
  importance: number;
  resolved_at: ISODateTime | null;
  apply_error: string | null;
  apply_metadata: Record<string, unknown>;
  created_at: ISODateTime;
  updated_at: ISODateTime;
}

export interface ReflectionListOut {
  items: Reflection[];
}

export interface ReflectionConfirmOut {
  reflection: Reflection;
  applied: boolean;
  apply_metadata: Record<string, unknown>;
}

export interface ReflectionRunOut {
  candidates_proposed: number;
  candidates_persisted: number;
  candidates_deduplicated: number;
  error: string | null;
}

// ---------- Twin evolution (Sprint 8) ----------
//
// Evolution events record durable, user-authorized changes that
// actually took effect. The mobile UI uses the event_type to pick
// copy — `profile_confirmed`/`memory_learned`/`memory_consolidated`/
// `goal_updated` all phrase as "Your Twin learned…", while
// `insight_acknowledged` phrases as "You acknowledged…" to preserve
// the Sprint 7 founder decision that an insight is NOT identity
// mutation.

export type EvolutionEventType =
  | 'memory_learned'
  | 'memory_consolidated'
  | 'goal_updated'
  | 'profile_confirmed'
  | 'insight_acknowledged';

export interface EvolutionEvent {
  id: UUID;
  user_id: UUID;
  twin_id: UUID;
  event_type: EvolutionEventType;
  reflection_id: UUID | null;
  memory_id: UUID | null;
  goal_id: UUID | null;
  profile_field: string | null;
  summary: string;
  created_at: ISODateTime;
}

export interface EvolutionListOut {
  items: EvolutionEvent[];
}
