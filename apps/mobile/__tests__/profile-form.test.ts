/**
 * Pure-function tests for the Sprint 9 profile edit screen helpers.
 *
 * These helpers are the entire data path from the form state to the
 * PATCH /v1/twin payload. Pinning them in jest means a save flow is
 * provably correct without needing a React Native renderer.
 */

import {
  basicProfileToRows,
  buildProfilePatch,
  rowsToBasicProfile,
  STYLE_NOTES_MAX,
  validateProfileForm,
} from '@/lib/profileForm';

describe('basicProfileToRows', () => {
  test('empty / null input yields an empty row list', () => {
    expect(basicProfileToRows(undefined)).toEqual([]);
    expect(basicProfileToRows(null)).toEqual([]);
    expect(basicProfileToRows({})).toEqual([]);
  });

  test('string values pass through', () => {
    expect(basicProfileToRows({ city: 'Lisbon', pronouns: 'they/them' }))
      .toEqual([
        { key: 'city', value: 'Lisbon' },
        { key: 'pronouns', value: 'they/them' },
      ]);
  });

  test('non-string values are coerced to string', () => {
    expect(basicProfileToRows({ age: 30, flag: true })).toEqual([
      { key: 'age', value: '30' },
      { key: 'flag', value: 'true' },
    ]);
  });

  test('null values render as empty string', () => {
    expect(basicProfileToRows({ city: null })).toEqual([
      { key: 'city', value: '' },
    ]);
  });
});

describe('rowsToBasicProfile', () => {
  test('drops rows with blank keys', () => {
    expect(
      rowsToBasicProfile([
        { key: '', value: 'orphan' },
        { key: '   ', value: 'spaces' },
        { key: 'city', value: 'Lisbon' },
      ]),
    ).toEqual({ city: 'Lisbon' });
  });

  test('coerces every value to string', () => {
    expect(
      rowsToBasicProfile([{ key: 'age', value: '30' as unknown as string }]),
    ).toEqual({ age: '30' });
  });

  test('trims the key but preserves the value', () => {
    expect(rowsToBasicProfile([{ key: '  city  ', value: ' Lisbon ' }]))
      .toEqual({ city: ' Lisbon ' });
  });
});

describe('validateProfileForm', () => {
  test('passes when notes are within the cap', () => {
    expect(
      validateProfileForm({
        preset: 'warm',
        notes: 'x'.repeat(STYLE_NOTES_MAX),
        rows: [],
      }),
    ).toEqual({ ok: true, error: null });
  });

  test('rejects notes over the cap after trimming', () => {
    const v = validateProfileForm({
      preset: 'warm',
      notes: '  ' + 'x'.repeat(STYLE_NOTES_MAX + 5) + '  ',
      rows: [],
    });
    expect(v.ok).toBe(false);
    expect(v.error).toContain(String(STYLE_NOTES_MAX));
  });
});

describe('buildProfilePatch', () => {
  test('produces the exact PATCH /v1/twin shape', () => {
    const patch = buildProfilePatch({
      preset: 'warm',
      notes: '  Prefer short replies.  ',
      rows: [
        { key: 'city', value: 'Lisbon' },
        { key: '', value: 'orphan' },
        { key: 'pronouns', value: 'they/them' },
      ],
    });
    expect(patch).toEqual({
      communication_style_preset: 'warm',
      communication_style_notes: 'Prefer short replies.',
      basic_profile: {
        city: 'Lisbon',
        pronouns: 'they/them',
      },
    });
  });

  test('blank notes become null (unset)', () => {
    const patch = buildProfilePatch({
      preset: 'neutral',
      notes: '   ',
      rows: [],
    });
    expect(patch.communication_style_notes).toBeNull();
  });

  test('empty basic_profile is an empty object', () => {
    const patch = buildProfilePatch({
      preset: 'terse',
      notes: '',
      rows: [],
    });
    expect(patch.basic_profile).toEqual({});
  });
});
