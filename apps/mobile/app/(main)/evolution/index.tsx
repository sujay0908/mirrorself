/**
 * Twin evolution screen (Sprint 8).
 *
 * Append-only history of durable, user-authorized changes that actually
 * took effect. Rejected reflections do NOT appear here. Pending
 * candidates do NOT appear here — those live in the Reflections screen
 * under the "Your Twin noticed…" framing.
 *
 * UX contract (founder decision #3):
 *
 * - `profile_confirmed` / `memory_learned` / `memory_consolidated` /
 *   `goal_updated` render as "Your Twin learned…" — these each
 *   represent an actual durable change the user authorized.
 * - `insight_acknowledged` renders as "You acknowledged…" — Sprint 7
 *   founder decision #1 pins that an insight confirmation is NOT
 *   identity mutation, so we don't phrase it as "learned".
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

import { api } from '@/api/client';
import type { EvolutionEvent, EvolutionEventType } from '@/api/types';

function evolutionLead(event_type: EvolutionEventType): string {
  if (event_type === 'insight_acknowledged') return 'You acknowledged';
  return 'Your Twin learned';
}

function evolutionTitle(event: EvolutionEvent): string {
  switch (event.event_type) {
    case 'memory_learned':
      return 'A new memory';
    case 'memory_consolidated':
      return 'Two memories merged';
    case 'goal_updated':
      return 'A goal note added';
    case 'profile_confirmed':
      return event.profile_field
        ? `Profile · ${event.profile_field}`
        : 'A profile change';
    case 'insight_acknowledged':
      return 'An insight';
  }
}

function evolutionTone(event_type: EvolutionEventType): {
  bg: string;
  label: string;
  labelColor: string;
} {
  if (event_type === 'insight_acknowledged') {
    return { bg: '#fef3c7', label: 'Insight', labelColor: '#92400e' };
  }
  if (event_type === 'profile_confirmed') {
    return { bg: '#dbeafe', label: 'Profile', labelColor: '#1e40af' };
  }
  if (event_type === 'memory_consolidated') {
    return { bg: '#e0e7ff', label: 'Memory dedup', labelColor: '#3730a3' };
  }
  if (event_type === 'goal_updated') {
    return { bg: '#dcfce7', label: 'Goal', labelColor: '#166534' };
  }
  return { bg: '#ecfeff', label: 'Memory', labelColor: '#155e75' };
}

export default function EvolutionScreen() {
  const [items, setItems] = useState<EvolutionEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    const res = await api.listEvolution(50);
    setItems(res.items);
  }, []);

  useEffect(() => {
    load()
      .catch((e) => Alert.alert('Could not load evolution', String(e)))
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

  return (
    <View style={styles.container}>
      <Stack.Screen options={{ title: 'What your Twin learned' }} />
      {loading ? (
        <ActivityIndicator style={{ marginTop: 40 }} />
      ) : (
        <FlatList
          data={items}
          keyExtractor={(e) => e.id}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
          }
          renderItem={({ item }) => {
            const tone = evolutionTone(item.event_type);
            return (
              <View style={styles.card}>
                <View style={styles.cardHeader}>
                  <Text
                    style={[
                      styles.badge,
                      { backgroundColor: tone.bg, color: tone.labelColor },
                    ]}
                  >
                    {tone.label}
                  </Text>
                  <Text style={styles.ts}>
                    {new Date(item.created_at).toLocaleString()}
                  </Text>
                </View>
                <Text style={styles.lead}>{evolutionLead(item.event_type)}</Text>
                <Text style={styles.title}>{evolutionTitle(item)}</Text>
                <Text style={styles.summary}>{item.summary}</Text>
              </View>
            );
          }}
          ListEmptyComponent={
            <View style={styles.empty}>
              <Text style={styles.emptyTitle}>
                Nothing to show here yet
              </Text>
              <Text style={styles.emptyBody}>
                As you confirm memories and reflections, your Twin&apos;s
                evolution history will show up here. Pending suggestions
                live under Reflections — those don&apos;t count as
                evolution until you confirm them.
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
    gap: 6,
  },
  cardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  badge: {
    paddingHorizontal: 10,
    paddingVertical: 2,
    borderRadius: 8,
    fontSize: 11,
    fontWeight: '700',
  },
  ts: { color: '#6b7280', fontSize: 12 },
  lead: {
    fontSize: 12,
    color: '#6b7280',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginTop: 4,
    fontWeight: '600',
  },
  title: { fontSize: 16, fontWeight: '700', color: '#111827' },
  summary: { fontSize: 13, color: '#374151', lineHeight: 18 },
  empty: { alignItems: 'center', marginTop: 60, padding: 24 },
  emptyTitle: { fontSize: 18, fontWeight: '700', marginBottom: 6 },
  emptyBody: {
    textAlign: 'center',
    color: '#6b7280',
    fontSize: 14,
    lineHeight: 20,
  },
});
