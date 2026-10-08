/**
 * Twin Self-Portrait screen (Sprint 9).
 *
 * Four deterministic sections composed server-side from
 * already-authorized data. No LLM. No narrative generation. Opening
 * this screen does NOT create any evolution event, does NOT touch any
 * memory or goal, and does NOT change profile state.
 *
 * UX contract (Sprint 7/8 copy preserved):
 *   • profile_confirmed / memory_learned / memory_consolidated /
 *     goal_updated events are shown as "Your Twin learned…".
 *   • insight_acknowledged events are shown as "You acknowledged…".
 *     Sprint 7 Decision #1 is that an insight is acknowledgement,
 *     NOT identity mutation.
 */

import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { Stack, useRouter } from 'expo-router';

import { api, APIError } from '@/api/client';
import type {
  EvolutionLead,
  PortraitEvolution,
  TwinPortrait,
} from '@/api/types';

const TYPE_LABEL: Record<string, string> = {
  FACT: 'Facts',
  PREFERENCE: 'Preferences',
  EXPERIENCE: 'Experiences',
  GOAL: 'Goal memories',
};

function evolutionLead(lead: EvolutionLead): string {
  return lead === 'acknowledged' ? 'You acknowledged' : 'Your Twin learned';
}

function evolutionTitle(e: PortraitEvolution): string {
  switch (e.event_type) {
    case 'memory_learned':
      return 'A new memory';
    case 'memory_consolidated':
      return 'Two memories merged';
    case 'goal_updated':
      return 'A goal note added';
    case 'profile_confirmed':
      return 'A profile change';
    case 'insight_acknowledged':
      return 'An insight';
    default:
      return 'An update';
  }
}

export default function PortraitScreen() {
  const router = useRouter();
  const [portrait, setPortrait] = useState<TwinPortrait | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const p = await api.getTwinPortrait();
      setPortrait(p);
    } catch (e) {
      setError(e instanceof APIError ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    load().finally(() => setLoading(false));
  }, [load]);

  const onRefresh = async () => {
    setRefreshing(true);
    try {
      await load();
    } finally {
      setRefreshing(false);
    }
  };

  if (loading) {
    return (
      <View style={styles.center}>
        <Stack.Screen options={{ title: 'What your Twin knows about you' }} />
        <ActivityIndicator />
      </View>
    );
  }
  if (error && !portrait) {
    return (
      <View style={styles.center}>
        <Stack.Screen options={{ title: 'What your Twin knows about you' }} />
        <Text style={styles.errorTitle}>Could not load portrait</Text>
        <Text style={styles.errorBody}>{error}</Text>
        <Pressable
          onPress={() => {
            setLoading(true);
            load().finally(() => setLoading(false));
          }}
          style={[styles.btn, styles.btnPrimary]}
        >
          <Text style={styles.btnPrimaryText}>Try again</Text>
        </Pressable>
      </View>
    );
  }
  if (!portrait) {
    return (
      <View style={styles.center}>
        <Stack.Screen options={{ title: 'What your Twin knows about you' }} />
        <Text>No Twin yet.</Text>
      </View>
    );
  }

  const bp = portrait.profile.basic_profile;
  const bpKeys = Object.keys(bp ?? {});

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
      }
    >
      <Stack.Screen options={{ title: 'What your Twin knows about you' }} />

      {/* How I speak to you */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>How I speak to you</Text>
        <View style={styles.row}>
          <Text style={styles.label}>Style</Text>
          <Text style={styles.value}>{portrait.profile.style_preset}</Text>
        </View>
        {portrait.profile.style_notes ? (
          <>
            <Text style={styles.label}>Notes</Text>
            <Text style={styles.body}>{portrait.profile.style_notes}</Text>
          </>
        ) : null}
        {bpKeys.length > 0 ? (
          <>
            <Text style={styles.label}>Basic profile</Text>
            {bpKeys.map((k) => (
              <View key={k} style={styles.kv}>
                <Text style={styles.kvKey}>{k}</Text>
                <Text style={styles.kvValue}>{String(bp[k])}</Text>
              </View>
            ))}
          </>
        ) : null}
        <Pressable
          onPress={() => router.push('/(main)/profile')}
          style={[styles.btn, styles.btnPrimary, styles.editBtn]}
        >
          <Text style={styles.btnPrimaryText}>Edit profile</Text>
        </Pressable>
      </View>

      {/* What I remember about you */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>What I remember about you</Text>
        <Text style={styles.summary}>
          {portrait.memory_summary.total_count}{' '}
          {portrait.memory_summary.total_count === 1 ? 'memory' : 'memories'} in
          total.
        </Text>
        <View style={styles.typeGrid}>
          {Object.entries(portrait.memory_summary.counts_by_type).map(
            ([type, count]) => (
              <View key={type} style={styles.typeTile}>
                <Text style={styles.typeTileCount}>{count}</Text>
                <Text style={styles.typeTileLabel}>
                  {TYPE_LABEL[type] ?? type}
                </Text>
              </View>
            ),
          )}
        </View>
        {portrait.memory_summary.top_memories.length > 0 ? (
          <>
            <Text style={styles.subhead}>Top memories (by importance)</Text>
            {portrait.memory_summary.top_memories.map((m) => (
              <Pressable
                key={m.id}
                onPress={() =>
                  router.push({
                    pathname: '/(main)/memories/[id]',
                    params: { id: m.id },
                  })
                }
                style={styles.memoryRow}
              >
                <View style={styles.memoryRowHeader}>
                  <Text style={styles.memoryBadge}>{m.type}</Text>
                  <Text style={styles.memoryImportance}>
                    importance {m.importance.toFixed(2)}
                  </Text>
                </View>
                <Text style={styles.memorySnippet}>{m.snippet}</Text>
              </Pressable>
            ))}
          </>
        ) : (
          <Text style={styles.empty}>
            Nothing yet. As you confirm memory suggestions, they&apos;ll show
            up here.
          </Text>
        )}
      </View>

      {/* What you're working on */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>What you&apos;re working on</Text>
        {portrait.active_goals.length === 0 ? (
          <Text style={styles.empty}>No active goals.</Text>
        ) : (
          portrait.active_goals.map((g) => (
            <Pressable
              key={g.id}
              onPress={() =>
                router.push({
                  pathname: '/(main)/goals/[id]',
                  params: { id: g.id },
                })
              }
              style={styles.goalRow}
            >
              <View style={styles.memoryRowHeader}>
                <Text style={styles.goalPriority}>priority {g.priority}</Text>
                {g.target_date ? (
                  <Text style={styles.memoryImportance}>
                    by {new Date(g.target_date).toLocaleDateString()}
                  </Text>
                ) : null}
              </View>
              <Text style={styles.goalTitle}>{g.title}</Text>
              {g.description ? (
                <Text style={styles.goalDesc}>{g.description}</Text>
              ) : null}
            </Pressable>
          ))
        )}
      </View>

      {/* What I've noticed recently */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>What I&apos;ve noticed recently</Text>
        {portrait.recent_evolution.length === 0 ? (
          <Text style={styles.empty}>
            As you confirm reflections, they&apos;ll show up here.
          </Text>
        ) : (
          portrait.recent_evolution.map((e) => (
            <View key={e.id} style={styles.evoRow}>
              <Text style={styles.evoLead}>{evolutionLead(e.lead)}</Text>
              <Text style={styles.evoTitle}>{evolutionTitle(e)}</Text>
              <Text style={styles.evoBody}>{e.summary}</Text>
              <Text style={styles.evoDate}>
                {new Date(e.created_at).toLocaleString()}
              </Text>
            </View>
          ))
        )}
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#f9fafb' },
  content: { padding: 12, gap: 12 },
  center: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
    gap: 12,
    backgroundColor: '#f9fafb',
  },
  card: {
    backgroundColor: '#ffffff',
    padding: 14,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: '#e5e7eb',
    gap: 8,
  },
  cardTitle: { fontSize: 15, fontWeight: '700', color: '#111827' },
  summary: { fontSize: 14, color: '#374151' },
  label: {
    fontSize: 11,
    fontWeight: '700',
    color: '#4b5563',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginTop: 8,
  },
  value: { fontSize: 14, color: '#111827', textTransform: 'capitalize' },
  body: { fontSize: 13, color: '#111827', lineHeight: 18 },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  kv: { flexDirection: 'row', justifyContent: 'space-between', paddingTop: 2 },
  kvKey: { fontSize: 13, color: '#6b7280' },
  kvValue: { fontSize: 13, color: '#111827', fontWeight: '600' },
  subhead: {
    fontSize: 12,
    fontWeight: '700',
    color: '#4b5563',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginTop: 10,
  },
  typeGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 4 },
  typeTile: {
    backgroundColor: '#eef2ff',
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 8,
    alignItems: 'center',
    minWidth: 70,
  },
  typeTileCount: { fontSize: 18, fontWeight: '700', color: '#312e81' },
  typeTileLabel: { fontSize: 11, color: '#4338ca', marginTop: 2 },
  memoryRow: {
    paddingVertical: 8,
    borderTopWidth: 1,
    borderTopColor: '#f3f4f6',
    gap: 4,
  },
  memoryRowHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  memoryBadge: {
    backgroundColor: '#eef2ff',
    color: '#4338ca',
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 8,
    fontSize: 11,
    fontWeight: '700',
  },
  memoryImportance: { fontSize: 12, color: '#6b7280' },
  memorySnippet: { fontSize: 13, color: '#111827', lineHeight: 18 },
  goalRow: {
    paddingVertical: 8,
    borderTopWidth: 1,
    borderTopColor: '#f3f4f6',
    gap: 4,
  },
  goalPriority: {
    backgroundColor: '#dcfce7',
    color: '#166534',
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 8,
    fontSize: 11,
    fontWeight: '700',
  },
  goalTitle: { fontSize: 14, color: '#111827', fontWeight: '600' },
  goalDesc: { fontSize: 12, color: '#6b7280', lineHeight: 16 },
  evoRow: {
    paddingVertical: 8,
    borderTopWidth: 1,
    borderTopColor: '#f3f4f6',
    gap: 2,
  },
  evoLead: {
    fontSize: 11,
    color: '#6b7280',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    fontWeight: '600',
  },
  evoTitle: { fontSize: 14, color: '#111827', fontWeight: '700' },
  evoBody: { fontSize: 13, color: '#374151', lineHeight: 18 },
  evoDate: { fontSize: 11, color: '#9ca3af' },
  empty: { color: '#6b7280', fontSize: 13, paddingVertical: 6 },
  editBtn: { marginTop: 10, alignSelf: 'flex-start' },
  btn: {
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderRadius: 10,
  },
  btnPrimary: { backgroundColor: '#4338ca' },
  btnPrimaryText: { color: '#ffffff', fontWeight: '700' },
  errorTitle: { fontSize: 16, fontWeight: '700', color: '#b91c1c' },
  errorBody: {
    textAlign: 'center',
    color: '#6b7280',
    fontSize: 13,
    lineHeight: 18,
  },
});
