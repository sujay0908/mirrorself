/**
 * Pure helpers for the Sprint 9 profile edit screen.
 *
 * Factored out so a node-only jest run can pin:
 *   • how `basic_profile` is serialised in and out of the key/value
 *     editor rows,
 *   • how a form state becomes a `TwinProfilePatch` payload for the
 *     existing PATCH /v1/twin endpoint,
 *   • that the save payload coerces every value to a string (Sprint 9
 *     client-side guard until the backend tightens the shape).
 */

import type {
  CommunicationStylePreset,
  TwinProfilePatch,
} from '@/api/types';

export interface BasicProfileRow {
  key: string;
  value: string;
}

export const STYLE_NOTES_MAX = 500;

export function basicProfileToRows(
  bp: Record<string, unknown> | null | undefined,
): BasicProfileRow[] {
  if (!bp) return [];
  return Object.entries(bp).map(([k, v]) => ({
    key: k,
    value: v === null || v === undefined ? '' : String(v),
  }));
}

export function rowsToBasicProfile(
  rows: BasicProfileRow[],
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const row of rows) {
    const k = row.key.trim();
    if (!k) continue;
    // Explicit string coercion. Sprint 9 brief: until the backend
    // tightens `basic_profile`, every value is stored as text.
    out[k] = String(row.value);
  }
  return out;
}

export interface ProfileFormState {
  preset: CommunicationStylePreset;
  notes: string;
  rows: BasicProfileRow[];
}

export interface ProfileFormValidation {
  ok: boolean;
  error: string | null;
}

export function validateProfileForm(
  state: ProfileFormState,
): ProfileFormValidation {
  if (state.notes.trim().length > STYLE_NOTES_MAX) {
    return {
      ok: false,
      error: `Style notes are limited to ${STYLE_NOTES_MAX} characters.`,
    };
  }
  return { ok: true, error: null };
}

export function buildProfilePatch(state: ProfileFormState): TwinProfilePatch {
  const trimmed = state.notes.trim();
  return {
    communication_style_preset: state.preset,
    communication_style_notes: trimmed.length ? trimmed : null,
    basic_profile: rowsToBasicProfile(state.rows),
  };
}
