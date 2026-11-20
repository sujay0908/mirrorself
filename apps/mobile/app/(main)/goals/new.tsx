/**
 * New goal: a title, an optional note, and how much it matters.
 * Target dates are set later from the goal itself, to keep this quick.
 */

import { useState } from 'react';
import { KeyboardAvoidingView, Platform, StyleSheet, Text, View } from 'react-native';
import { useRouter } from 'expo-router';

import { api } from '@/api/client';
import { PRIORITIES } from '@/lib/format';
import { userErrorMessage } from '@/lib/user-errors';
import { Button, Chip, Notice, Page, TextField } from '@/ui/kit';
import { colors, space, type } from '@/ui/theme';

export default function NewGoalScreen() {
  const router = useRouter();
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [priority, setPriority] = useState(3);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    const trimmed = title.trim();
    if (!trimmed) {
      setError('Give your goal a title.');
      return;
    }
    setError(null);
    setSaving(true);
    try {
      const goal = await api.createGoal({
        title: trimmed,
        description: description.trim() || null,
        priority,
      });
      router.replace({ pathname: '/(main)/goals/[id]', params: { id: goal.id } });
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
      <Page contentStyle={styles.content}>
        <Text style={styles.lead}>
          What are you working towards? Your Twin keeps active goals in mind when
          you talk.
        </Text>
        <TextField
          label="Goal"
          value={title}
          onChangeText={setTitle}
          placeholder="e.g. Run a 10K by spring"
          maxLength={200}
          autoFocus
        />
        <TextField
          label="Why it matters"
          hint="Optional — how you'll know you're done, or what's driving it."
          value={description}
          onChangeText={setDescription}
          placeholder="I want to feel fitter and have something to train for."
          multiline
          maxLength={4000}
        />
        <View style={styles.section}>
          <Text style={styles.label}>Priority</Text>
          <View style={styles.priorities}>
            {PRIORITIES.map((p) => (
              <Chip
                key={p.value}
                label={p.label}
                selected={priority === p.value}
                onPress={() => setPriority(p.value)}
              />
            ))}
          </View>
        </View>
        {error ? <Notice tone="danger" body={error} /> : null}
        <Button
          title="Create goal"
          size="lg"
          onPress={save}
          loading={saving}
          disabled={!title.trim()}
          style={styles.submit}
        />
      </Page>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.bg },
  content: { gap: space.lg },
  lead: { ...type.body, color: colors.muted },
  section: { gap: space.sm },
  label: { fontSize: 14, fontWeight: '700', color: colors.ink },
  priorities: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm },
  submit: { marginTop: space.sm },
});
