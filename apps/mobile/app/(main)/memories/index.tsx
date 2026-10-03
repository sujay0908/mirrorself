/**
 * Memories list screen (Sprint 4, DF6).
 *
 * Newest-first (server default), with a horizontal strip of type filters.
 * Tapping a row opens memory detail. "Review candidates" surfaces the
 * triage flow prominently when there is nothing pending-looking to show.
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
import type { Memory, MemoryType } from '@/api/types';

const TYPE_OPTIONS: Array<{ label: string; value: MemoryType | 'ALL' }> = [
  { label: 'All', value: 'ALL' },
  { label: 'Facts', value: 'FACT' },
  { label: 'Preferences', value: 'PREFERENCE' },
  { label: 'Experiences', value: 'EXPERIENCE' },
  { label: 'Goals', value: 'GOAL' },
];

export default function MemoriesScreen() {
  const router = useRouter();
  const [items, setItems] = useState<Memory[]>([]);
  const [filter, setFilter] = useState<MemoryType | 'ALL'>('ALL');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (f: MemoryType | 'ALL') => {
    const res = await api.listMemories(f === 'ALL' ? undefined : f);
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
      <Stack.Screen
        options={{
          title: 'Memories',
          headerRight: () => (
            <Pressable
              onPress={() => router.push('/(main)/candidates')}
              style={styles.headerBtn}
            >
              <Text style={styles.headerBtnText}>Review</Text>
            </Pressable>
          ),
        }}
      />
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.filters}
      >
        {TYPE_OPTIONS.map((opt) => (
          <Pressable
            key={opt.value}
            onPress={() => setFilter(opt.value)}
            style={[
              styles.chip,
              filter === opt.value && styles.chipActive,
            ]}
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
          keyExtractor={(m) => m.id}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
          }
          renderItem={({ item }) => (
            <Pressable
              onPress={() =>
                router.push({
                  pathname: '/(main)/memories/[id]',
                  params: { id: item.id },
                })
              }
              style={styles.row}
            >
              <View style={styles.rowHeader}>
                <Text style={styles.badge}>{item.type}</Text>
                <Text style={styles.ts}>
                  {new Date(item.created_at).toLocaleDateString()}
                </Text>
              </View>
              <Text style={styles.content} numberOfLines={2}>
                {item.content}
              </Text>
            </Pressable>
          )}
          ListEmptyComponent={
            <Text style={styles.empty}>No memories yet.</Text>
          }
        />
      )}
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
  chipActive: {
    backgroundColor: '#4338ca',
    borderColor: '#4338ca',
  },
  chipText: { color: '#374151', fontSize: 13 },
  chipTextActive: { color: '#ffffff', fontWeight: '600' },
  row: {
    backgroundColor: '#ffffff',
    marginHorizontal: 12,
    marginVertical: 4,
    padding: 12,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#e5e7eb',
  },
  rowHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 6,
  },
  badge: {
    backgroundColor: '#eef2ff',
    color: '#4338ca',
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 8,
    fontSize: 11,
    fontWeight: '700',
  },
  ts: { color: '#6b7280', fontSize: 12 },
  content: { color: '#111827', fontSize: 14, lineHeight: 20 },
  empty: { textAlign: 'center', marginTop: 60, color: '#6b7280' },
  headerBtn: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    marginRight: 8,
  },
  headerBtnText: { color: '#4338ca', fontWeight: '600' },
});
