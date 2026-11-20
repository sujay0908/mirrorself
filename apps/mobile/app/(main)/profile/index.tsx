/**
 * Edit profile: how your Twin talks to you, and the basics it should always
 * know. Uses the existing PATCH /v1/twin — no new way to change the profile.
 *
 * Rules kept from the original screen:
 *   • Four style presets (neutral / terse / warm / analytical).
 *   • Style notes up to 500 characters (the server allows 2000; the shorter
 *     limit keeps them useful).
 *   • Basic facts are label/value pairs, saved as text exactly as typed.
 *   • Nothing saves until you press Save. On success the session's Twin is
 *     refreshed and you go back; on failure you stay with your edits intact.
 */

import { useState } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { useRouter } from 'expo-router';

import { api } from '@/api/client';
import type { CommunicationStylePreset, TwinProfile } from '@/api/types';
import { LoadingScreen } from '@/components/LoadingScreen';
import { STYLES } from '@/lib/format';
import { goBackOr } from '@/lib/navigation';
import {
  basicProfileToRows,
  buildProfilePatch,
  STYLE_NOTES_MAX,
  type BasicProfileRow,
  validateProfileForm,
} from '@/lib/profileForm';
import { userErrorMessage } from '@/lib/user-errors';
import { useSession } from '@/state/session';
import { Alert } from '@/ui/alert';
import {
  Button,
  ButtonRow,
  Card,
  Notice,
  OptionGrid,
  Page,
  SectionTitle,
  TextField,
  WEB_NO_OUTLINE,
} from '@/ui/kit';
import { colors, radius, space, type } from '@/ui/theme';

export default function ProfileEditScreen() {
  const twin = useSession((s) => s.twin);
  // The form must never start from defaults: Save sends every field, so a
  // form opened before the Twin loaded (a refresh, or an opened link) used to
  // overwrite the real profile with "neutral" and empty notes. The (main)
  // layout already waits for the Twin; this guard keeps that true here.
  if (!twin) return <LoadingScreen />;
  return <ProfileForm key={twin.id} name={twin.display_name} profile={twin.profile} />;
}

function ProfileForm({ name, profile }: { name: string; profile: TwinProfile }) {
  const router = useRouter();
  const setTwin = useSession((s) => s.setTwin);

  const [preset, setPreset] = useState<CommunicationStylePreset>(
    profile.communication_style_preset ?? 'neutral',
  );
  const [notes, setNotes] = useState<string>(profile.communication_style_notes ?? '');
  const [rows, setRows] = useState<BasicProfileRow[]>(() =>
    basicProfileToRows(profile.basic_profile),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function addRow() {
    setRows((prev) => [...prev, { key: '', value: '' }]);
  }

  function removeRow(index: number) {
    setRows((prev) => prev.filter((_, i) => i !== index));
  }

  function updateRow(index: number, patch: Partial<BasicProfileRow>) {
    setRows((prev) => prev.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  async function onSave() {
    setError(null);
    const state = { preset, notes, rows };
    const validation = validateProfileForm(state);
    if (!validation.ok) {
      setError(validation.error);
      return;
    }
    setSaving(true);
    try {
      const updated = await api.patchTwin(buildProfilePatch(state));
      setTwin(updated);
      Alert.alert('Saved', `${name} will use your updated profile from the next reply.`);
      goBackOr(router);
    } catch (e) {
      setError(userErrorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <KeyboardAvoidingView
      style={styles.flex}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <Page>
        <SectionTitle>How should {name} talk to you?</SectionTitle>
        <OptionGrid options={STYLES} value={preset} onChange={setPreset} />

        <SectionTitle>Anything else about how you like to talk?</SectionTitle>
        <TextField
          hint="Optional. Your Twin keeps this in mind in every reply."
          value={notes}
          onChangeText={setNotes}
          multiline
          maxLength={STYLE_NOTES_MAX}
          counter={{ value: notes.length, max: STYLE_NOTES_MAX }}
          placeholder="e.g. Keep mornings short. Ask before giving advice."
        />

        <SectionTitle>The basics</SectionTitle>
        <Card>
          <Text style={type.small}>
            Short facts {name} should always know — where you live, what you do, who
            matters to you.
          </Text>
          {rows.map((row, idx) => (
            <View key={idx} style={styles.kvRow}>
              <TextInput
                value={row.key}
                onChangeText={(t) => updateRow(idx, { key: t })}
                placeholder="Label, e.g. City"
                placeholderTextColor={colors.faint}
                accessibilityLabel={`Label ${idx + 1}`}
                style={[styles.kvInput, styles.kvKey, WEB_NO_OUTLINE]}
                autoCapitalize="none"
                autoCorrect={false}
              />
              <TextInput
                value={row.value}
                onChangeText={(t) => updateRow(idx, { value: t })}
                placeholder="e.g. Bengaluru"
                placeholderTextColor={colors.faint}
                accessibilityLabel={`Value ${idx + 1}`}
                style={[styles.kvInput, styles.kvValue, WEB_NO_OUTLINE]}
              />
              <Pressable
                onPress={() => removeRow(idx)}
                accessibilityRole="button"
                accessibilityLabel={`Remove ${row.key || 'this fact'}`}
                hitSlop={6}
                style={({ pressed }) => [styles.remove, pressed && styles.removePressed]}
              >
                <Text style={styles.removeText}>✕</Text>
              </Pressable>
            </View>
          ))}
          <Button title="＋ Add a fact" variant="ghost" size="sm" onPress={addRow} style={styles.add} />
        </Card>

        {error ? <Notice tone="danger" body={error} /> : null}

        <ButtonRow>
          <Button title="Cancel" variant="secondary" onPress={() => goBackOr(router)} />
          <Button title="Save changes" onPress={onSave} loading={saving} />
        </ButtonRow>
      </Page>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.bg },
  kvRow: { flexDirection: 'row', gap: space.sm, alignItems: 'center' },
  kvInput: {
    backgroundColor: colors.surfaceAlt,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: space.md,
    paddingVertical: 10,
    fontSize: 15,
    color: colors.ink,
    minWidth: 0,
  },
  kvKey: { flex: 2 },
  kvValue: { flex: 3 },
  remove: {
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
  },
  removePressed: { backgroundColor: colors.dangerSoft },
  removeText: { color: colors.danger, fontSize: 15, fontWeight: '700' },
  add: { alignSelf: 'flex-start' },
});
