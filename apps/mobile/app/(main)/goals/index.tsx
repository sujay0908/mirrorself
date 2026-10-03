/**
 * Goals list screen (Sprint 4, DF6).
 *
 * Shows active goals first, with a status filter to see paused/achieved/
 * abandoned. "+ New goal" opens the create screen.
 */

import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { Stack, useRouter } from 'expo-router';

import { api } from '@/api/client';
import type { Goal, GoalStatus } from '@/api/types';

const STATUS_OPTIONS: Array<{ label: string; value: GoalStatus | 'ALL' }> = [
  { label: 'Active', value: 'active' },
  { label: 'Paused', value: 'paused' },
  { label: 'Achieved', value: 'achieved' },
  { label: 'Abandoned', value: 'abandoned' },
  { label: 'All', value: 'ALL' },
];

const STATUS_COLORS: Record<GoalStatus, { bg: string; fg: string }> = {
  active: { bg: '#dcfce7', fg: '#15803d' },
  paused: { bg: '#fef3c7', fg: '#92400e' },
  achieved: { bg: '#dbeafe', fg: '#1d4ed8' },
  abandoned: { bg: '#f3f4f6', fg: '#6b7280' },
};

export default function GoalsScreen() {
  const router = useRouter();
  const [items, setItems] = useState<Goal[]>([]);
  const [filter, setFilter] = useState<GoalStatus | 'ALL'>('active');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (f: GoalStatus | 'ALL') => {
    const res = await api.listGoals(f === 'ALL' ? undefined : f);
    setItems(res.items);
  }, []);

  useEffect(() => {
    setLoading(true);
    load(filter).finally(() => setLoading(false));
  }, [filter, load]);

  const onRefresh = async () => {
    setRefreshing(true);
    try {
      await load(filter);
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <View style={styles.container}>
      <Stack.Screen options={{ title: 'Goals' }} />
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.filters}
      >
        {STATUS_OPTIONS.map((opt) => (
          <Pressable
            key={opt.value}
            onPress={() => setFilter(opt.value)}
            style={[styles.chip, filter === opt.value && styles.chipActive]}
          >
            <Text
              style={[
                styles.chipText,
                filter === opt.value && styles.chipTextActive,
              ]}
            >
              {opt.label}
            </Text>
          </Pressable>
        ))}
      </ScrollView>
      {loading ? (
        <ActivityIndicator style={{ marginTop: 40 }} />
      ) : (
        <FlatList
          data={items}
          keyExtractor={(g) => g.id}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
          }
          renderItem={({ item }) => {
            const colors = STATUS_COLORS[item.status];
            return (
              <Pressable
                onPress={() =>
                  router.push({
                    pathname: '/(main)/goals/[id]',
                    params: { id: item.id },
                  })
                }
                style={styles.row}
              >
                <View style={styles.rowHeader}>
                  <Text style={styles.title} numberOfLines={2}>
                    {item.title}
                  </Text>
                  <View
                    style={[
                      styles.statusPill,
                      { backgroundColor: colors.bg },
                    ]}
                  >
                    <Text
                      style={[styles.statusText, { color: colors.fg }]}
                    >
                      {item.status}
                    </Text>
                  </View>
                </View>
                <Text style={styles.meta}>
                  priority {item.priority}
                  {item.target_date
                    ? ` · due ${new Date(item.target_date).toLocaleDateString()}`
                    : ''}
                </Text>
                {item.description ? (
                  <Text style={styles.desc} numberOfLines={2}>
                    {item.description}
                  </Text>
                ) : null}
              </Pressable>
            );
          }}
          ListEmptyComponent={
            <Text style={styles.empty}>
              {filter === 'active'
                ? 'No active goals. Tap "+ New goal" to add one.'
                : 'No goals in this view.'}
            </Text>
          }
        />
      )}
      <Pressable
        onPress={() => router.push('/(main)/goals/new')}
        style={styles.fab}
      >
        <Text style={styles.fabText}>+ New goal</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#f9fafb' },
  filters: {
    paddingHorizontal: 12,
    paddingVertical: 10,
    gap: 8,
    flexDirection: 'row',
  },
  chip: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: '#d1d5db',
    backgroundColor: '#ffffff',
  },
  chipActive: { backgroundColor: '#4338ca', borderColor: '#4338ca' },
  chipText: { color: '#374151', fontSize: 13 },
  chipTextActive: { color: '#ffffff', fontWeight: '600' },
  row: {
    backgroundColor: '#ffffff',
    marginHorizontal: 12,
    marginVertical: 4,
    padding: 14,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#e5e7eb',
    gap: 6,
  },
  rowHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 8,
  },
  title: { flex: 1, fontSize: 16, fontWeight: '700', color: '#111827' },
  statusPill: {
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 999,
    alignSelf: 'flex-start',
  },
  statusText: { fontSize: 11, fontWeight: '700', textTransform: 'uppercase' },
  meta: { fontSize: 12, color: '#6b7280' },
  desc: { fontSize: 13, color: '#374151' },
  empty: { textAlign: 'center', marginTop: 60, color: '#6b7280' },
  fab: {
    position: 'absolute',
    right: 20,
    bottom: 24,
    backgroundColor: '#4f46e5',
    paddingHorizontal: 20,
    paddingVertical: 12,
    borderRadius: 999,
  },
  fabText: { color: '#ffffff', fontWeight: '700' },
});
