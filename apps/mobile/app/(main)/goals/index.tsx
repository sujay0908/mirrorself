/**
 * Goals list: active goals first, with a filter for the rest.
 */

import { useCallback, useEffect, useState } from 'react';
import { FlatList, Pressable, RefreshControl, StyleSheet, Text, View } from 'react-native';
import { useRouter } from 'expo-router';

import { api } from '@/api/client';
import type { Goal, GoalStatus } from '@/api/types';
import { goalStatus, priorityLabel, shortDate } from '@/lib/format';
import { useRefreshOnFocus } from '@/lib/use-refresh-on-focus';
import { userErrorMessage } from '@/lib/user-errors';
import { Card, EmptyState, ErrorState, FilterBar, listContent, Loading, Tag } from '@/ui/kit';
import { colors, radius, shadow, space, type } from '@/ui/theme';

type Filter = GoalStatus | 'ALL';

const STATUS_OPTIONS: ReadonlyArray<{ label: string; value: Filter }> = [
  { label: 'Active', value: 'active' },
  { label: 'Paused', value: 'paused' },
  { label: 'Achieved', value: 'achieved' },
  { label: 'Dropped', value: 'abandoned' },
  { label: 'All', value: 'ALL' },
];

export default function GoalsScreen() {
  const router = useRouter();
  const [items, setItems] = useState<Goal[]>([]);
  const [filter, setFilter] = useState<Filter>('active');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (f: Filter) => {
    try {
      const res = await api.listGoals(f === 'ALL' ? undefined : f);
      setItems(res.items);
      setError(null);
    } catch (e) {
      setError(userErrorMessage(e));
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    load(filter).finally(() => setLoading(false));
  }, [filter, load]);

  // New goals, status changes and edits happen on screens above this one.
  useRefreshOnFocus(() => load(filter));

  const onRefresh = async () => {
    setRefreshing(true);
    try {
      await load(filter);
    } finally {
      setRefreshing(false);
    }
  };

  const newGoal = () => router.push('/(main)/goals/new');

  return (
    <View style={styles.container}>
      <FilterBar options={STATUS_OPTIONS} value={filter} onChange={setFilter} />
      {loading ? (
        <Loading />
      ) : error && items.length === 0 ? (
        <ErrorState
          title="Could not load your goals"
          message={error}
          onRetry={() => {
            setLoading(true);
            load(filter).finally(() => setLoading(false));
          }}
        />
      ) : (
        <FlatList
          data={items}
          keyExtractor={(g) => g.id}
          contentContainerStyle={listContent}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
          renderItem={({ item }) => {
            const s = goalStatus(item.status);
            return (
              <Card
                onPress={() =>
                  router.push({ pathname: '/(main)/goals/[id]', params: { id: item.id } })
                }
              >
                <View style={styles.rowHeader}>
                  <Text style={styles.title} numberOfLines={2}>
                    {item.title}
                  </Text>
                  <Tag label={s.label} tone={s.tone} />
                </View>
                <Text style={type.caption}>
                  {priorityLabel(item.priority)} priority
                  {item.target_date ? ` · by ${shortDate(item.target_date)}` : ''}
                </Text>
                {item.description ? (
                  <Text style={styles.desc} numberOfLines={2}>
                    {item.description}
                  </Text>
                ) : null}
              </Card>
            );
          }}
          ListEmptyComponent={
            filter === 'active' ? (
              <EmptyState
                emoji="🎯"
                title="No active goals yet"
                body="Goals tell your Twin what matters to you right now, so it can keep them in mind when you talk."
                action={{ title: 'Add your first goal', onPress: newGoal }}
              />
            ) : (
              <EmptyState emoji="🗂️" title="Nothing here" body="No goals in this view." />
            )
          }
        />
      )}
      {items.length > 0 || filter !== 'active' ? (
        <Pressable
          onPress={newGoal}
          accessibilityRole="button"
          accessibilityLabel="New goal"
          style={({ pressed }) => [styles.fab, pressed && styles.fabPressed]}
        >
          <Text style={styles.fabText}>＋ New goal</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  rowHeader: { flexDirection: 'row', justifyContent: 'space-between', gap: space.sm },
  title: { flex: 1, ...type.heading },
  desc: { ...type.small, color: colors.text },
  fab: {
    position: 'absolute',
    right: space.xl,
    bottom: space.xxl,
    backgroundColor: colors.primary,
    paddingHorizontal: space.xl,
    paddingVertical: 14,
    borderRadius: radius.pill,
    ...shadow.raised,
  },
  fabPressed: { backgroundColor: colors.primaryPressed },
  fabText: { color: colors.onPrimary, fontWeight: '800', fontSize: 15 },
});
