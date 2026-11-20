/**
 * One-time onboarding: name the twin and pick a communication style.
 */

import { useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useRouter } from 'expo-router';

import { api } from '@/api/client';
import type { CommunicationStylePreset } from '@/api/types';
import { STYLES } from '@/lib/format';
import { userErrorMessage } from '@/lib/user-errors';
import { useSession } from '@/state/session';
import { Avatar, Button, Notice, OptionGrid, TextField } from '@/ui/kit';
import { colors, space, type } from '@/ui/theme';

export default function CreateTwinScreen() {
  const router = useRouter();
  const setTwin = useSession((s) => s.setTwin);
  const [name, setName] = useState('');
  const [style, setStyle] = useState<CommunicationStylePreset>('warm');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit() {
    const trimmed = name.trim();
    if (!trimmed) {
      setError('Give your Twin a name.');
      return;
    }
    setError(null);
    setLoading(true);
    try {
      const twin = await api.createTwin({ name: trimmed, communication_style: style });
      setTwin(twin);
      router.replace('/(main)/home');
    } catch (err) {
      setError(userErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <KeyboardAvoidingView
      style={styles.flex}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        <View style={styles.column}>
          <View style={styles.header}>
            <Avatar name={name || 'Twin'} size={64} />
            <Text style={type.display}>Meet your Twin</Text>
            <Text style={styles.lead}>
              Give it a name and choose how it should talk to you. You can change
              both later.
            </Text>
          </View>

          <TextField
            label="Name"
            placeholder="e.g. Nova"
            value={name}
            onChangeText={setName}
            editable={!loading}
            maxLength={60}
            onSubmitEditing={onSubmit}
          />

          <View style={styles.section}>
            <Text style={styles.label}>How should it talk to you?</Text>
            <OptionGrid options={STYLES} value={style} onChange={setStyle} />
          </View>

          {error ? <Notice tone="danger" body={error} /> : null}

          <Button
            title={name.trim() ? `Create ${name.trim()}` : 'Create my Twin'}
            size="lg"
            onPress={onSubmit}
            loading={loading}
            disabled={!name.trim()}
          />
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.bg },
  scroll: { flexGrow: 1, justifyContent: 'center', padding: space.xl },
  column: { width: '100%', maxWidth: 520, alignSelf: 'center', gap: space.xl },
  header: { alignItems: 'center', gap: space.sm },
  lead: { ...type.body, color: colors.muted, textAlign: 'center', maxWidth: 380 },
  section: { gap: space.sm },
  label: { fontSize: 14, fontWeight: '700', color: colors.ink },
});
