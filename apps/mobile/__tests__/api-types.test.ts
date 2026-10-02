/**
 * Type-level smoke test — the shape of the API types stays in sync with the
 * backend Pydantic schemas. This is a compile-time check.
 */

import type { Message, Twin } from '@/api/types';

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
  created_at: '2026-09-25T00:00:00Z',
};

test('type smoke passes', () => {
  expect(_twinSample.display_name).toBe('Aurora');
  expect(_messageSample.role).toBe('twin');
});
