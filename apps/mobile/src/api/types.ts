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
