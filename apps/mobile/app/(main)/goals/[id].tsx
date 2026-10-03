/**
 * Goal detail screen (Sprint 4, DF6).
 *
 * View + edit + status transition (achieve / abandon / pause / resume).
 * Illegal transitions are hidden rather than disabled so the UI doesn't
 * tempt the user into a 409.
 */

import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';

import { api, APIError } from '@/api/client';
import type { Goal, GoalStatus } from '@/api/types';

const LEGAL_NEXT: Record<GoalStatus, GoalStatus[]> = {
  active: ['achieved', 'abandoned', 'paused'],
  paused: ['active', 'achieved', 'abandoned'],
  achieved: [],
  abandoned: [],
};

const NEXT_LABEL: Record<GoalStatus, string> = {
  active: 'Resume',
  paused: 'Pause',
  achieved: 'Achieve',
  abandoned: 'Abandon',
};

const STATUS_COLORS: Record<GoalStatus, { bg: string; fg: string }> = {
  active: { bg: '#dcfce7', fg: '#15803d' },
  paused: { bg: '#fef3c7', fg: '#92400e' },
  achieved: { bg: '#dbeafe', fg: '#1d4ed8' },
  abandoned: { bg: '#f3f4f6', fg: '#6b7280' },
};

export default function GoalDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [goal, setGoal] = useState<Goal | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [draftTitle, setDraftTitle] = useState('');
  const [draftDesc, setDraftDesc] = useState('');
  const [draftPriority, setDraftPriority] = useState(3);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    const g = await api.getGoal(id);
    setGoal(g);
    setDraftTitle(g.title);
    setDraftDesc(g.description ?? '');
    setDraftPriority(g.priority);
  }, [id]);

  useEffect(() => {
    load()
      .catch((e) => Alert.alert('Could not load goal', String(e)))
      .finally(() => setLoading(false));
  }, [load]);

  async function save() {
    if (!id || !goal) return;
    const t = draftTitle.trim();
    if (!t) {
      Alert.alert('Title cannot be empty.');
      return;
    }
    setSaving(true);
    try {
      const updated = await api.patchGoal(id, {
        title: t !== goal.title ? t : undefined,
        description:
          draftDesc.trim() !== (goal.description ?? '')
            ? draftDesc.trim() || null
            : undefined,
        priority: draftPriority !== goal.priority ? draftPriority : undefined,
      });
      setGoal(updated);
      setEditing(false);
    } catch (e) {
      Alert.alert(
        'Could not save',
        e instanceof APIError ? e.message : String(e),
      );
    } finally {
      setSaving(false);
    }
  }

  async function changeStatus(next: GoalStatus) {
    if (!id || !goal) return;
    try {
      const updated = await api.patchGoal(id, { status: next });
      setGoal(updated);
    } catch (e) {
      Alert.alert(
        'Could not update status',
        e instanceof APIError ? e.message : String(e),
      );
    }
  }

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator />
      </View>
    );
  }
  if (!goal) {
    return (
      <View style={styles.center}>
        <Text>Goal not found.</Text>
      </View>
    );
  }

  const colors = STATUS_COLORS[goal.status];
  const nextStates = LEGAL_NEXT[goal.status];

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
    >
      <Stack.Screen options={{ title: goal.title }} />

      <View style={styles.headerRow}>
        <View style={[styles.statusPill, { backgroundColor: colors.bg }]}>
          <Text style={[styles.statusText, { color: colors.fg }]}>
            {goal.status}
          </Text>
        </View>
        <Text style={styles.date}>
          since {new Date(goal.status_changed_at).toLocaleDateString()}
        </Text>
      </View>

      {editing ? (
        <>
          <Text style={styles.label}>Title</Text>
          <TextInput
            value={draftTitle}
            onChangeText={setDraftTitle}
            style={styles.input}
            maxLength={200}
          />
          <Text style={styles.label}>Description</Text>
          <TextInput
            value={draftDesc}
            onChangeText={setDraftDesc}
            style={[styles.input, styles.multiline]}
            multiline
            maxLength={4000}
          />
          <Text style={styles.label}>Priority</Text>
          <View style={styles.priorityRow}>
            {[1, 2, 3, 4, 5].map((p) => (
              <Pressable
                key={p}
                onPress={() => setDraftPriority(p)}
                style={[
                  styles.priorityChip,
                  draftPriority === p && styles.priorityChipActive,
                ]}
              >
                <Text
                  style={[
                    styles.priorityText,
                    draftPriority === p && styles.priorityTextActive,
                  ]}
                >
                  {p}
                </Text>
              </Pressable>
            ))}
          </View>
          <View style={styles.row}>
            <Pressable
              onPress={() => {
                setDraftTitle(goal.title);
                setDraftDesc(goal.description ?? '');
                setDraftPriority(goal.priority);
                setEditing(false);
              }}
              style={[styles.btn, styles.btnSecondary]}
            >
              <Text style={styles.btnSecondaryText}>Cancel</Text>
            </Pressable>
            <Pressable
              onPress={save}
              disabled={saving}
              style={[styles.btn, styles.btnPrimary]}
            >
              <Text style={styles.btnPrimaryText}>
                {saving ? '…' : 'Save'}
              </Text>
            </Pressable>
          </View>
        </>
      ) : (
        <>
          <Text style={styles.title}>{goal.title}</Text>
          <Text style={styles.meta}>
            priority {goal.priority}
            {goal.target_date
              ? ` · due ${new Date(goal.target_date).toLocaleDateString()}`
              : ''}
          </Text>
          {goal.description ? (
            <Text style={styles.desc}>{goal.description}</Text>
          ) : null}

          <View style={styles.row}>
            <Pressable
              onPress={() => router.back()}
              style={[styles.btn, styles.btnSecondary]}
            >
              <Text style={styles.btnSecondaryText}>Back</Text>
            </Pressable>
            <Pressable
              onPress={() => setEditing(true)}
              style={[styles.btn, styles.btnPrimary]}
            >
              <Text style={styles.btnPrimaryText}>Edit</Text>
            </Pressable>
          </View>

          {nextStates.length > 0 ? (
            <>
              <Text style={styles.sectionTitle}>Change status</Text>
              <View style={styles.row}>
                {nextStates.map((next) => (
                  <Pressable
                    key={next}
                    onPress={() => changeStatus(next)}
                    style={[styles.btn, styles.btnSecondary]}
                  >
                    <Text style={styles.btnSecondaryText}>
                      {NEXT_LABEL[next]}
                    </Text>
                  </Pressable>
                ))}
              </View>
            </>
          ) : (
            <Text style={styles.terminal}>
              This goal is {goal.status} and cannot change further.
            </Text>
          )}
        </>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#f9fafb' },
  content: { padding: 16, gap: 12 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  statusPill: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 999,
  },
  statusText: { fontSize: 11, fontWeight: '700', textTransform: 'uppercase' },
  date: { color: '#6b7280', fontSize: 12 },
  title: { fontSize: 22, fontWeight: '700', color: '#111827' },
  meta: { color: '#6b7280' },
  desc: {
    fontSize: 15,
    lineHeight: 22,
    color: '#111827',
    backgroundColor: '#ffffff',
    padding: 14,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#e5e7eb',
  },
  label: { fontSize: 13, color: '#374151', fontWeight: '600', marginTop: 8 },
  input: {
    backgroundColor: '#ffffff',
    borderWidth: 1,
    borderColor: '#d1d5db',
    borderRadius: 12,
    padding: 12,
    fontSize: 16,
  },
  multiline: { minHeight: 100, textAlignVertical: 'top' },
  priorityRow: { flexDirection: 'row', gap: 8 },
  priorityChip: {
    width: 44,
    height: 44,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: '#d1d5db',
    backgroundColor: '#ffffff',
    alignItems: 'center',
    justifyContent: 'center',
  },
  priorityChipActive: {
    borderColor: '#4338ca',
    backgroundColor: '#eef2ff',
  },
  priorityText: { color: '#374151', fontWeight: '700' },
  priorityTextActive: { color: '#4338ca' },
  row: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: 8,
    flexWrap: 'wrap',
  },
  btn: { paddingHorizontal: 14, paddingVertical: 10, borderRadius: 10 },
  btnPrimary: { backgroundColor: '#4f46e5' },
  btnPrimaryText: { color: '#ffffff', fontWeight: '700' },
  btnSecondary: {
    backgroundColor: '#ffffff',
    borderWidth: 1,
    borderColor: '#d1d5db',
  },
  btnSecondaryText: { color: '#374151', fontWeight: '600' },
  sectionTitle: {
    marginTop: 16,
    fontSize: 14,
    fontWeight: '700',
    color: '#111827',
  },
  terminal: {
    marginTop: 16,
    textAlign: 'center',
    color: '#6b7280',
    fontStyle: 'italic',
  },
});
