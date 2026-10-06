/**
 * Reflections screen (Sprint 7).
 *
 * The Twin can read a bounded view of the user's own confirmed memories,
 * active goals and recent conversation turns and PROPOSE user-confirmable
 * observations. Four kinds — `profile_update`, `memory_dedup`,
 * `goal_update`, `insight`. The LLM proposes; the user confirms;
 * only confirmation can create durable changes.
 *
 * UX contract (founder decisions):
 *   • INSIGHT confirmation is acknowledgement only — no Memory is
 *     created, no profile mutation. That is why the Keep button on an
 *     insight is labelled "Acknowledge".
 *   • PROFILE_UPDATE must expose current and proposed values, source
 *     memories and rationale BEFORE the user confirms. The card renders
 *     a diff block so "Why does my Twin think this about me?" has an
 *     answer before the button is pressed.
 */

import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { Stack } from 'expo-router';

import { api, APIError } from '@/api/client';
import type {
  GoalUpdatePayload,
  InsightPayload,
  MemoryDedupPayload,
  ProfileUpdatePayload,
  Reflection,
  ReflectionPayload,
} from '@/api/types';

function renderValue(value: unknown): string {
  if (value === null || value === undefined) return '(none)';
  if (typeof value === 'string') return value || '(empty)';
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function KindBadge({ kind }: { kind: Reflection['kind'] }) {
  const label =
    kind === 'profile_update'
      ? 'Profile'
      : kind === 'memory_dedup'
        ? 'Memory dedup'
        : kind === 'goal_update'
          ? 'Goal update'
          : 'Insight';
  return <Text style={styles.badge}>{label}</Text>;
}

function ProfileUpdateCard({ payload }: { payload: ProfileUpdatePayload }) {
  return (
    <View style={styles.body}>
      <Text style={styles.fieldLabel}>Field</Text>
      <Text style={styles.fieldValue}>{payload.field}</Text>

      <Text style={styles.fieldLabel}>Current value</Text>
      <Text style={styles.diffCurrent}>{renderValue(payload.current_value)}</Text>

      <Text style={styles.fieldLabel}>Proposed value</Text>
      <Text style={styles.diffProposed}>{renderValue(payload.proposed_value)}</Text>

      <Text style={styles.rationaleLabel}>Why</Text>
      <Text style={styles.rationaleText}>{payload.rationale}</Text>
    </View>
  );
}

function MemoryDedupCard({ payload }: { payload: MemoryDedupPayload }) {
  return (
    <View style={styles.body}>
      <Text style={styles.explain}>
        Your Twin thinks these two memories say the same thing. Confirming
        will mark one as superseded by the other. The superseded memory is
        kept — the memories screen still shows it, and you can un-supersede
        it. New chats will use the canonical one.
      </Text>
      <Text style={styles.fieldLabel}>Superseded memory</Text>
      <Text style={styles.monoId}>{payload.superseded_memory_id}</Text>
      <Text style={styles.fieldLabel}>Canonical memory</Text>
      <Text style={styles.monoId}>{payload.canonical_memory_id}</Text>

      <Text style={styles.rationaleLabel}>Why</Text>
      <Text style={styles.rationaleText}>{payload.rationale}</Text>
    </View>
  );
}

function GoalUpdateCard({ payload }: { payload: GoalUpdatePayload }) {
  return (
    <View style={styles.body}>
      <Text style={styles.explain}>
        Non-destructive: confirming records a note on this goal&apos;s
        history. The goal&apos;s title, status and priority are not
        touched.
      </Text>
      <Text style={styles.fieldLabel}>Goal</Text>
      <Text style={styles.monoId}>{payload.goal_id}</Text>
      <Text style={styles.fieldLabel}>Note to add</Text>
      <Text style={styles.diffProposed}>{payload.note}</Text>
      <Text style={styles.rationaleLabel}>Why</Text>
      <Text style={styles.rationaleText}>{payload.rationale}</Text>
    </View>
  );
}

function InsightCard({ payload }: { payload: InsightPayload }) {
  return (
    <View style={styles.body}>
      <Text style={styles.insightHeadline}>{payload.headline}</Text>
      <Text style={styles.insightBody}>{payload.body}</Text>
      <Text style={styles.rationaleLabel}>Why</Text>
      <Text style={styles.rationaleText}>{payload.rationale}</Text>
      <Text style={styles.insightNote}>
        Acknowledging an insight saves it as a reflection record. It does
        not create a memory or change your profile.
      </Text>
    </View>
  );
}

function PayloadBody({ payload }: { payload: ReflectionPayload }) {
  switch (payload.kind) {
    case 'profile_update':
      return <ProfileUpdateCard payload={payload} />;
    case 'memory_dedup':
      return <MemoryDedupCard payload={payload} />;
    case 'goal_update':
      return <GoalUpdateCard payload={payload} />;
    case 'insight':
      return <InsightCard payload={payload} />;
  }
}

function SourceList({ item }: { item: Reflection }) {
  if (!item.source_memory_ids.length && !item.source_goal_ids.length) {
    return null;
  }
  return (
    <View style={styles.sources}>
      {item.source_memory_ids.length ? (
        <>
          <Text style={styles.sourcesLabel}>Source memories</Text>
          {item.source_memory_ids.map((mid) => (
            <Text key={mid} style={styles.sourceId}>
              {mid}
            </Text>
          ))}
        </>
      ) : null}
      {item.source_goal_ids.length ? (
        <>
          <Text style={styles.sourcesLabel}>Source goals</Text>
          {item.source_goal_ids.map((gid) => (
            <Text key={gid} style={styles.sourceId}>
              {gid}
            </Text>
          ))}
        </>
      ) : null}
    </View>
  );
}

export default function ReflectionsScreen() {
  const [items, setItems] = useState<Reflection[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [running, setRunning] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    const res = await api.listReflections('pending');
    setItems(res.items);
  }, []);

  useEffect(() => {
    load()
      .catch((e) => Alert.alert('Could not load reflections', String(e)))
      .finally(() => setLoading(false));
  }, [load]);

  const onRefresh = async () => {
    setRefreshing(true);
    try {
      await load();
    } finally {
      setRefreshing(false);
    }
  };

  async function runReflection() {
    setRunning(true);
    try {
      const out = await api.runReflections();
      if (out.error) {
        Alert.alert(
          'Reflection run failed',
          `The Twin could not propose anything new (${out.error}).`,
        );
      } else {
        Alert.alert(
          'Reflection run complete',
          `Proposed ${out.candidates_proposed}, kept ${out.candidates_persisted}, deduplicated ${out.candidates_deduplicated}.`,
        );
      }
      await load();
    } catch (e) {
      Alert.alert(
        'Reflection run failed',
        e instanceof APIError ? e.message : String(e),
      );
    } finally {
      setRunning(false);
    }
  }

  async function confirmOne(id: string) {
    setBusyId(id);
    try {
      const out = await api.confirmReflection(id);
      if (!out.applied) {
        Alert.alert(
          'Confirmed, but could not apply',
          String(out.reflection.apply_error ?? 'Unknown error.'),
        );
      }
      setItems((prev) => prev.filter((c) => c.id !== id));
    } catch (e) {
      Alert.alert(
        'Could not confirm',
        e instanceof APIError ? e.message : String(e),
      );
    } finally {
      setBusyId(null);
    }
  }

  async function rejectOne(id: string) {
    setBusyId(id);
    try {
      await api.rejectReflection(id);
      setItems((prev) => prev.filter((c) => c.id !== id));
    } catch (e) {
      Alert.alert(
        'Could not reject',
        e instanceof APIError ? e.message : String(e),
      );
    } finally {
      setBusyId(null);
    }
  }

  return (
    <View style={styles.container}>
      <Stack.Screen
        options={{
          title: 'Reflections',
          headerRight: () => (
            <Pressable
              onPress={runReflection}
              disabled={running}
              style={styles.headerBtn}
            >
              <Text style={styles.headerBtnText}>
                {running ? '…' : 'Run now'}
              </Text>
            </Pressable>
          ),
        }}
      />
      {loading ? (
        <ActivityIndicator style={{ marginTop: 40 }} />
      ) : (
        <FlatList
          data={items}
          keyExtractor={(c) => c.id}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
          }
          renderItem={({ item }) => {
            const confirmLabel =
              item.kind === 'insight' ? 'Acknowledge' : 'Confirm';
            return (
              <View style={styles.card}>
                <View style={styles.cardHeader}>
                  <KindBadge kind={item.kind} />
                  <Text style={styles.conf}>
                    conf {item.confidence.toFixed(2)} · imp{' '}
                    {item.importance.toFixed(2)}
                  </Text>
                </View>
                <PayloadBody payload={item.proposed_payload} />
                <SourceList item={item} />
                <View style={styles.actions}>
                  <Pressable
                    disabled={busyId === item.id}
                    onPress={() => rejectOne(item.id)}
                    style={[styles.btn, styles.btnReject]}
                  >
                    <Text style={styles.btnRejectText}>Reject</Text>
                  </Pressable>
                  <Pressable
                    disabled={busyId === item.id}
                    onPress={() => confirmOne(item.id)}
                    style={[styles.btn, styles.btnConfirm]}
                  >
                    <Text style={styles.btnConfirmText}>
                      {busyId === item.id ? '…' : confirmLabel}
                    </Text>
                  </Pressable>
                </View>
              </View>
            );
          }}
          ListEmptyComponent={
            <View style={styles.empty}>
              <Text style={styles.emptyTitle}>No pending reflections</Text>
              <Text style={styles.emptyBody}>
                Tap &quot;Run now&quot; after a few chats and your Twin
                will propose observations here. Only you can confirm them.
              </Text>
            </View>
          }
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#f9fafb' },
  card: {
    backgroundColor: '#ffffff',
    marginHorizontal: 12,
    marginVertical: 6,
    padding: 14,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: '#e5e7eb',
    gap: 12,
  },
  cardHeader: { flexDirection: 'row', justifyContent: 'space-between' },
  badge: {
    backgroundColor: '#ecfeff',
    color: '#155e75',
    paddingHorizontal: 10,
    paddingVertical: 2,
    borderRadius: 8,
    fontSize: 11,
    fontWeight: '700',
  },
  conf: { color: '#6b7280', fontSize: 12 },
  body: { gap: 6 },
  fieldLabel: {
    fontSize: 11,
    fontWeight: '700',
    color: '#4b5563',
    marginTop: 4,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  fieldValue: { fontSize: 14, color: '#111827' },
  diffCurrent: {
    fontSize: 14,
    color: '#111827',
    backgroundColor: '#f3f4f6',
    padding: 10,
    borderRadius: 8,
    fontFamily: 'Menlo',
  },
  diffProposed: {
    fontSize: 14,
    color: '#065f46',
    backgroundColor: '#ecfdf5',
    padding: 10,
    borderRadius: 8,
    fontFamily: 'Menlo',
  },
  monoId: {
    fontSize: 12,
    color: '#374151',
    fontFamily: 'Menlo',
    backgroundColor: '#f3f4f6',
    padding: 8,
    borderRadius: 8,
  },
  rationaleLabel: {
    fontSize: 11,
    fontWeight: '700',
    color: '#4b5563',
    marginTop: 6,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  rationaleText: {
    fontSize: 13,
    color: '#374151',
    lineHeight: 18,
    fontStyle: 'italic',
  },
  explain: {
    fontSize: 12,
    color: '#4b5563',
    lineHeight: 17,
    backgroundColor: '#f9fafb',
    padding: 10,
    borderRadius: 8,
  },
  insightHeadline: { fontSize: 16, fontWeight: '700', color: '#111827' },
  insightBody: { fontSize: 14, color: '#111827', lineHeight: 20 },
  insightNote: {
    fontSize: 12,
    color: '#6b7280',
    marginTop: 6,
    fontStyle: 'italic',
  },
  sources: {
    gap: 4,
    paddingTop: 8,
    borderTopWidth: 1,
    borderTopColor: '#f3f4f6',
  },
  sourcesLabel: {
    fontSize: 11,
    fontWeight: '700',
    color: '#4b5563',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginTop: 4,
  },
  sourceId: { fontSize: 11, color: '#6b7280', fontFamily: 'Menlo' },
  actions: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: 8,
    paddingTop: 4,
  },
  btn: {
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 10,
  },
  btnConfirm: { backgroundColor: '#4f46e5' },
  btnConfirmText: { color: '#ffffff', fontWeight: '700' },
  btnReject: {
    backgroundColor: '#ffffff',
    borderWidth: 1,
    borderColor: '#d1d5db',
  },
  btnRejectText: { color: '#374151', fontWeight: '600' },
  empty: { alignItems: 'center', marginTop: 60, padding: 24 },
  emptyTitle: { fontSize: 18, fontWeight: '700', marginBottom: 6 },
  emptyBody: {
    textAlign: 'center',
    color: '#6b7280',
    fontSize: 14,
    lineHeight: 20,
  },
  headerBtn: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    marginRight: 8,
  },
  headerBtnText: { color: '#4338ca', fontWeight: '600' },
});
