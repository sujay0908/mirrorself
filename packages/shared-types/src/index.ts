/**
 * Cross-package API type definitions.
 *
 * Sprint 1: hand-authored, mirrored from `apps/api/app/**/schemas.py`.
 * Sprint 2+: replaced by `generated.ts` produced from
 * `apps/api/app/main.py`'s OpenAPI schema by `openapi-typescript`. CI diffs
 * this file against the generated output; drift is a build failure.
 */

export type UUID = string;
export type ISODateTime = string;

export type CommunicationStylePreset =
  | 'neutral'
  | 'terse'
  | 'warm'
  | 'analytical';

export type MessageRole = 'user' | 'twin' | 'system';

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

export interface Conversation {
  id: UUID;
  twin_id: UUID;
  title: string | null;
  created_at: ISODateTime;
  updated_at: ISODateTime;
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
  created_at: ISODateTime;
}
