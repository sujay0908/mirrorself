/**
 * Goal detail: view, edit, and move between states (achieve / pause /
 * resume / drop). Only the moves the server allows are offered, so the UI
 * never invites a conflict.
 */

import { useCallback, useEffect, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';

import { api } from '@/api/client';
import type { Goal, GoalStatus } from '@/api/types';
import {
  goalStatus,
  goalStatusAction,
  PRIORITIES,
  priorityLabel,
  shortDate,
} from '@/lib/format';
import { goBackOr } from '@/lib/navigation';
import { userErrorMessage } from '@/lib/user-errors';
import { Alert } from '@/ui/alert';
import {
  Button,
  ButtonRow,
  Card,
  Centered,
  Chip,
  ErrorState,
  Loading,
  Notice,
  Page,
  SectionTitle,
  Tag,
  TextField,
} from '@/ui/kit';
import { colors, space, type } from '@/ui/theme';

const LEGAL_NEXT: Record<GoalStatus, GoalStatus[]> = {
  active: ['achieved', 'paused', 'abandoned'],
  paused: ['active', 'achieved', 'abandoned'],
  achieved: [],
  abandoned: [],
};

export default function GoalDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [goal, setGoal] = useState<Goal | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [draftTitle, setDraftTitle] = useState('');
  const [draftDesc, setDraftDesc] = useState('');
  const [draftPriority, setDraftPriority] = useState(3);
  const [saving, setSaving] = useState(false);
  const [changing, setChanging] = useState<GoalStatus | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const g = await api.getGoal(id);
      setGoal(g);
      setDraftTitle(g.title);
      setDraftDesc(g.description ?? '');
      setDraftPriority(g.priority);
      setLoadError(null);
    } catch (e) {
      setLoadError(userErrorMessage(e));
    }
  }, [id]);

  useEffect(() => {
    load().finally(() => setLoading(false));
  }, [load]);

  async function save() {
    if (!id || !goal) return;
    const t = draftTitle.trim();
    if (!t) {
      Alert.alert('A goal needs a title.');
      return;
    }
    setSaving(true);
    try {
      const updated = await api.patchGoal(id, {
        title: t !== goal.title ? t : undefined,
        description:
          draftDesc.trim() !== (goal.description ?? '') ? draftDesc.trim() || null : undefined,
        priority: draftPriority !== goal.priority ? draftPriority : undefined,
      });
      setGoal(updated);
      setEditing(false);
    } catch (e) {
      Alert.alert('Could not save', userErrorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  async function changeStatus(next: GoalStatus) {
    if (!id || !goal) return;
    setChanging(next);
    try {
      const updated = await api.patchGoal(id, { status: next });
      setGoal(updated);
    } catch (e) {
      Alert.alert('Could not update this goal', userErrorMessage(e));
    } finally {
      setChanging(null);
    }
  }

  if (loading) return <Loading />;
  if (!goal) {
    return (
      <Centered>
        <ErrorState
          title="Could not open this goal"
          message={loadError ?? 'It may have been removed.'}
          onRetry={() => {
            setLoading(true);
            load().finally(() => setLoading(false));
          }}
        />
      </Centered>
    );
  }

  const s = goalStatus(goal.status);
  const nextStates = LEGAL_NEXT[goal.status];

  return (
    <Page>
      <Stack.Screen options={{ title: 'Goal' }} />

      {editing ? (
        <Card style={styles.card}>
          <TextField
            label="Goal"
            value={draftTitle}
            onChangeText={setDraftTitle}
            maxLength={200}
          />
          <TextField
            label="Why it matters"
            value={draftDesc}
            onChangeText={setDraftDesc}
            multiline
            maxLength={4000}
          />
          <Text style={styles.label}>Priority</Text>
          <View style={styles.priorities}>
            {PRIORITIES.map((p) => (
              <Chip
                key={p.value}
                label={p.label}
                selected={draftPriority === p.value}
                onPress={() => setDraftPriority(p.value)}
              />
            ))}
          </View>
          <ButtonRow>
            <Button
              title="Cancel"
              variant="secondary"
              onPress={() => {
                setDraftTitle(goal.title);
                setDraftDesc(goal.description ?? '');
                setDraftPriority(goal.priority);
                setEditing(false);
              }}
            />
            <Button title="Save" onPress={save} loading={saving} />
          </ButtonRow>
        </Card>
      ) : (
        <Card style={styles.card}>
          <View style={styles.metaRow}>
            <Tag label={`${s.emoji} ${s.label}`} tone={s.tone} />
            <Text style={type.caption}>since {shortDate(goal.status_changed_at)}</Text>
          </View>
          <Text style={styles.title}>{goal.title}</Text>
          <Text style={type.small}>
            {priorityLabel(goal.priority)} priority
            {goal.target_date ? ` · by ${shortDate(goal.target_date)}` : ''}
          </Text>
          {goal.description ? <Text style={styles.desc}>{goal.description}</Text> : null}
          <ButtonRow>
            <Button title="Back" variant="ghost" onPress={() => goBackOr(router)} />
            <Button title="Edit" variant="secondary" onPress={() => setEditing(true)} />
          </ButtonRow>
        </Card>
      )}

      {!editing && nextStates.length > 0 ? (
        <>
          <SectionTitle>Update progress</SectionTitle>
          <ButtonRow align="start">
            {nextStates.map((next) => (
              <Button
                key={next}
                title={goalStatusAction(next)}
                variant={next === 'achieved' ? 'primary' : next === 'abandoned' ? 'danger' : 'secondary'}
                loading={changing === next}
                disabled={changing !== null && changing !== next}
                onPress={() => changeStatus(next)}
              />
            ))}
          </ButtonRow>
        </>
      ) : null}

      {!editing && nextStates.length === 0 ? (
        <Notice
          tone={goal.status === 'achieved' ? 'success' : 'neutral'}
          title={goal.status === 'achieved' ? 'Nicely done 🎉' : 'This goal is closed'}
          body={
            goal.status === 'achieved'
              ? 'You achieved this goal. It stays here as part of your story.'
              : 'You dropped this goal. It stays here for reference.'
          }
        />
      ) : null}
    </Page>
  );
}

const styles = StyleSheet.create({
  card: { padding: space.xl, gap: space.md },
  metaRow: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  title: { ...type.title, fontSize: 22, lineHeight: 28 },
  desc: { ...type.body, color: colors.text },
  label: { fontSize: 14, fontWeight: '700', color: colors.ink },
  priorities: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm },
});
