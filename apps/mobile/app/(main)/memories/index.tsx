/**
 * Memories: everything your Twin has kept, newest first, filterable by kind.
 */

import { useCallback, useEffect, useState } from 'react';
import { FlatList, Pressable, RefreshControl, StyleSheet, Text, View } from 'react-native';
import { Stack, useRouter } from 'expo-router';

import { api } from '@/api/client';
import type { Memory, MemoryType } from '@/api/types';
import { memoryType, relativeTime } from '@/lib/format';
import { useRefreshOnFocus } from '@/lib/use-refresh-on-focus';
import { userErrorMessage } from '@/lib/user-errors';
import { Card, EmptyState, ErrorState, FilterBar, listContent, Loading, Tag } from '@/ui/kit';
import { colors, space, type } from '@/ui/theme';

type Filter = MemoryType | 'ALL';

const TYPE_OPTIONS: ReadonlyArray<{ label: string; value: Filter }> = [
  { label: 'All', value: 'ALL' },
  { label: 'Facts', value: 'FACT' },
  { label: 'Preferences', value: 'PREFERENCE' },
  { label: 'Experiences', value: 'EXPERIENCE' },
  { label: 'Goals', value: 'GOAL' },
];

export default function MemoriesScreen() {
  const router = useRouter();
  const [items, setItems] = useState<Memory[]>([]);
  const [filter, setFilter] = useState<Filter>('ALL');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (f: Filter) => {
    try {
      const res = await api.listMemories(f === 'ALL' ? undefined : f);
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

  // Edits and deletions happen on the detail screen above this one.
  useRefreshOnFocus(() => load(filter));

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
      <Stack.Screen
        options={{
          headerRight: () => (
            <Pressable
              onPress={() => router.push('/(main)/candidates')}
              accessibilityRole="button"
              hitSlop={8}
              style={styles.headerBtn}
            >
              <Text style={styles.headerBtnText}>Review</Text>
            </Pressable>
          ),
        }}
      />
      <FilterBar options={TYPE_OPTIONS} value={filter} onChange={setFilter} />
      {loading ? (
        <Loading />
      ) : error && items.length === 0 ? (
        <ErrorState
          title="Could not load your memories"
          message={error}
          onRetry={() => {
            setLoading(true);
            load(filter).finally(() => setLoading(false));
          }}
        />
      ) : (
        <FlatList
          data={items}
          keyExtractor={(m) => m.id}
          contentContainerStyle={listContent}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
          renderItem={({ item }) => {
            const t = memoryType(item.type);
            const replaced = Boolean(item.superseded_by_memory_id);
            return (
              <Card
                onPress={() =>
                  router.push({ pathname: '/(main)/memories/[id]', params: { id: item.id } })
                }
                style={replaced ? styles.replaced : null}
              >
                <View style={styles.rowHeader}>
                  <View style={styles.tags}>
                    <Tag label={`${t.emoji} ${t.label}`} tone={t.tone} />
                    {replaced ? <Tag label="Replaced" tone="warning" /> : null}
                  </View>
                  <Text style={type.caption}>{relativeTime(item.created_at)}</Text>
                </View>
                <Text style={[styles.content, replaced && styles.contentReplaced]} numberOfLines={3}>
                  {item.content}
                </Text>
              </Card>
            );
          }}
          ListEmptyComponent={
            filter === 'ALL' ? (
              <EmptyState
                emoji="🧠"
                title="No memories yet"
                body="When your Twin picks up something worth remembering in a chat, it asks you first. What you keep shows up here."
                action={{
                  title: 'Review suggestions',
                  onPress: () => router.push('/(main)/candidates'),
                }}
              />
            ) : (
              <EmptyState
                emoji={memoryType(filter).emoji}
                title={`No ${memoryType(filter).plural.toLowerCase()} yet`}
              />
            )
          }
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  rowHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: space.sm,
  },
  tags: { flexDirection: 'row', gap: 6, flexWrap: 'wrap', flex: 1 },
  content: { ...type.body, color: colors.ink },
  contentReplaced: { color: colors.muted },
  replaced: { backgroundColor: colors.surfaceAlt },
  headerBtn: { paddingHorizontal: space.md, paddingVertical: 6 },
  headerBtnText: { color: colors.primary, fontWeight: '700', fontSize: 15 },
});
