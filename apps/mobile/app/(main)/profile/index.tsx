/**
 * Profile edit screen (Sprint 9).
 *
 * The one mid-session surface for editing TwinProfile. Calls the
 * existing PATCH /v1/twin — Sprint 9 does NOT introduce a new
 * mutation path.
 *
 * UX contract:
 *   • style preset: the four shipped options (neutral / terse / warm
 *     / analytical).
 *   • style notes: free text up to 500 characters. The backend
 *     caps at 2000; the stricter mobile cap is a usability guard.
 *   • basic_profile: simple key/value editor. Until the backend
 *     tightens the shape we coerce every value to a string on save,
 *     so the server stores exactly what the user typed.
 *   • Explicit Save button. No autosave — the user authors the edit.
 *   • On success: refresh the session's Twin, show a one-line toast
 *     "The next reply will use your updated Twin profile.", nav back.
 *   • On failure: stay on screen, surface inline error, keep edits.
 */

import { useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { Stack, useRouter } from 'expo-router';

import { api, APIError } from '@/api/client';
import type { CommunicationStylePreset } from '@/api/types';
import {
  basicProfileToRows,
  buildProfilePatch,
  STYLE_NOTES_MAX,
  type BasicProfileRow,
  validateProfileForm,
} from '@/lib/profileForm';
import { useSession } from '@/state/session';

const STYLE_OPTIONS: Array<{ key: CommunicationStylePreset; label: string }> = [
  { key: 'neutral', label: 'Neutral' },
  { key: 'terse', label: 'Terse' },
  { key: 'warm', label: 'Warm' },
  { key: 'analytical', label: 'Analytical' },
];

export default function ProfileEditScreen() {
  const router = useRouter();
  const twin = useSession((s) => s.twin);
  const setTwin = useSession((s) => s.setTwin);

  const initial = useMemo(() => {
    const p = twin?.profile;
    return {
      preset: (p?.communication_style_preset ?? 'neutral') as CommunicationStylePreset,
      notes: p?.communication_style_notes ?? '',
      rows: basicProfileToRows(p?.basic_profile),
    };
  }, [twin]);

  const [preset, setPreset] = useState<CommunicationStylePreset>(initial.preset);
  const [notes, setNotes] = useState<string>(initial.notes);
  const [rows, setRows] = useState<BasicProfileRow[]>(initial.rows);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function addRow() {
    setRows((prev) => [...prev, { key: '', value: '' }]);
  }

  function removeRow(index: number) {
    setRows((prev) => prev.filter((_, i) => i !== index));
  }

  function updateRow(index: number, patch: Partial<BasicProfileRow>) {
    setRows((prev) =>
      prev.map((row, i) => (i === index ? { ...row, ...patch } : row)),
    );
  }

  async function onSave() {
    setError(null);
    const state = { preset, notes, rows };
    const validation = validateProfileForm(state);
    if (!validation.ok) {
      setError(validation.error);
      return;
    }
    const payload = buildProfilePatch(state);
    setSaving(true);
    try {
      const updated = await api.patchTwin(payload);
      setTwin(updated);
      Alert.alert(
        'Profile updated',
        'The next reply will use your updated Twin profile.',
      );
      router.back();
    } catch (e) {
      setError(e instanceof APIError ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <Stack.Screen options={{ title: 'Edit profile' }} />
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.sectionTitle}>Communication style</Text>
        <View style={styles.chipRow}>
          {STYLE_OPTIONS.map((opt) => (
            <Pressable
              key={opt.key}
              onPress={() => setPreset(opt.key)}
              style={[styles.chip, preset === opt.key && styles.chipActive]}
            >
              <Text
                style={[
                  styles.chipText,
                  preset === opt.key && styles.chipTextActive,
                ]}
              >
                {opt.label}
              </Text>
            </Pressable>
          ))}
        </View>

        <Text style={styles.sectionTitle}>Style notes</Text>
        <Text style={styles.hint}>
          Optional notes your Twin keeps in mind when it replies.
        </Text>
        <TextInput
          value={notes}
          onChangeText={setNotes}
          multiline
          maxLength={STYLE_NOTES_MAX}
          style={styles.notesInput}
          placeholder="e.g. Short replies in the morning."
        />
        <Text style={styles.counter}>
          {notes.length} / {STYLE_NOTES_MAX}
        </Text>

        <Text style={styles.sectionTitle}>Basic profile</Text>
        <Text style={styles.hint}>
          Short facts your Twin should always know. Values are saved as text.
        </Text>
        {rows.map((row, idx) => (
          <View key={idx} style={styles.kvRow}>
            <TextInput
              value={row.key}
              onChangeText={(t) => updateRow(idx, { key: t })}
              placeholder="key"
              style={[styles.kvInput, styles.kvInputKey]}
              autoCapitalize="none"
              autoCorrect={false}
            />
            <TextInput
              value={row.value}
              onChangeText={(t) => updateRow(idx, { value: t })}
              placeholder="value"
              style={[styles.kvInput, styles.kvInputValue]}
            />
            <Pressable
              onPress={() => removeRow(idx)}
              style={styles.kvRemoveBtn}
            >
              <Text style={styles.kvRemoveText}>✕</Text>
            </Pressable>
          </View>
        ))}
        <Pressable onPress={addRow} style={styles.addRow}>
          <Text style={styles.addRowText}>+ Add row</Text>
        </Pressable>

        {error ? <Text style={styles.error}>{error}</Text> : null}

        <View style={styles.actions}>
          <Pressable
            onPress={() => router.back()}
            style={[styles.btn, styles.btnSecondary]}
          >
            <Text style={styles.btnSecondaryText}>Cancel</Text>
          </Pressable>
          <Pressable
            onPress={onSave}
            disabled={saving}
            style={[styles.btn, styles.btnPrimary]}
          >
            {saving ? (
              <ActivityIndicator color="#ffffff" />
            ) : (
              <Text style={styles.btnPrimaryText}>Save</Text>
            )}
          </Pressable>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#f9fafb' },
  content: { padding: 16, gap: 10 },
  sectionTitle: {
    fontSize: 13,
    fontWeight: '700',
    color: '#111827',
    marginTop: 16,
  },
  hint: { fontSize: 12, color: '#6b7280', lineHeight: 17 },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 4 },
  chip: {
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: '#d1d5db',
    backgroundColor: '#ffffff',
  },
  chipActive: { backgroundColor: '#4338ca', borderColor: '#4338ca' },
  chipText: { color: '#374151', fontSize: 13 },
  chipTextActive: { color: '#ffffff', fontWeight: '600' },
  notesInput: {
    minHeight: 90,
    backgroundColor: '#ffffff',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#d1d5db',
    padding: 12,
    fontSize: 14,
    color: '#111827',
    textAlignVertical: 'top',
  },
  counter: {
    fontSize: 11,
    color: '#6b7280',
    textAlign: 'right',
    marginTop: -4,
  },
  kvRow: { flexDirection: 'row', gap: 6, alignItems: 'center' },
  kvInput: {
    backgroundColor: '#ffffff',
    borderRadius: 10,
    borderWidth: 1,
    borderColor: '#d1d5db',
    paddingHorizontal: 10,
    paddingVertical: 8,
    fontSize: 13,
    color: '#111827',
  },
  kvInputKey: { flex: 1 },
  kvInputValue: { flex: 2 },
  kvRemoveBtn: { paddingHorizontal: 8, paddingVertical: 6 },
  kvRemoveText: { color: '#b91c1c', fontSize: 16, fontWeight: '700' },
  addRow: { marginTop: 4, paddingVertical: 8 },
  addRowText: { color: '#4338ca', fontWeight: '600' },
  error: {
    color: '#b91c1c',
    fontSize: 13,
    marginTop: 8,
    backgroundColor: '#fee2e2',
    padding: 10,
    borderRadius: 10,
  },
  actions: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: 8,
    marginTop: 24,
  },
  btn: {
    paddingHorizontal: 20,
    paddingVertical: 10,
    borderRadius: 10,
    minWidth: 90,
    alignItems: 'center',
  },
  btnPrimary: { backgroundColor: '#4338ca' },
  btnPrimaryText: { color: '#ffffff', fontWeight: '700' },
  btnSecondary: {
    backgroundColor: '#ffffff',
    borderWidth: 1,
    borderColor: '#d1d5db',
  },
  btnSecondaryText: { color: '#374151', fontWeight: '600' },
});
