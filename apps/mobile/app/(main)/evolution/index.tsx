/**
 * Evolution: the history of changes you approved that actually took effect.
 *
 * Rejected reflections and pending suggestions never appear here. Learned
 * changes read "Your Twin learned…"; an acknowledged insight reads "You
 * acknowledged…", because seeing an insight does not change who the Twin
 * thinks you are.
 */

import { useCallback, useEffect, useState } from 'react';
import { FlatList, Pressable, RefreshControl, StyleSheet, Text, View } from 'react-native';
import { useRouter } from 'expo-router';

import { api } from '@/api/client';
import type { EvolutionEvent } from '@/api/types';
import { friendlyEvent, relativeTime } from '@/lib/format';
import { useRefreshOnFocus } from '@/lib/use-refresh-on-focus';
import { userErrorMessage } from '@/lib/user-errors';
import { useSession } from '@/state/session';
import { EmptyState, ErrorState, listContent, Loading } from '@/ui/kit';
import { colors, space, tones, type } from '@/ui/theme';

export default function EvolutionScreen() {
  const router = useRouter();
  const twinName = useSession((s) => s.twin?.display_name ?? 'Your Twin');
  const [items, setItems] = useState<EvolutionEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await api.listEvolution(50);
      setItems(res.items);
      setError(null);
    } catch (e) {
      setError(userErrorMessage(e));
    }
  }, []);

  useEffect(() => {
    load().finally(() => setLoading(false));
  }, [load]);

  useRefreshOnFocus(load);

  const onRefresh = async () => {
    setRefreshing(true);
    try {
      await load();
    } finally {
      setRefreshing(false);
    }
  };

  if (loading) return <Loading />;
  if (error && items.length === 0) {
    return (
      <ErrorState
        title="Could not load the history"
        message={error}
        onRetry={() => {
          setLoading(true);
          load().finally(() => setLoading(false));
        }}
      />
    );
  }

  return (
    <FlatList
      style={styles.list}
      data={items}
      keyExtractor={(e) => e.id}
      contentContainerStyle={[listContent, styles.content]}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
      ListHeaderComponent={
        items.length > 0 ? (
          <Text style={styles.intro}>
            Every change here is one you approved. Newest first.
          </Text>
        ) : null
      }
      renderItem={({ item, index }) => {
        const e = friendlyEvent(item.event_type, item.summary, item.profile_field);
        const t = tones[e.tone];
        const target =
          item.memory_id
            ? () => router.push({ pathname: '/(main)/memories/[id]', params: { id: item.memory_id as string } })
            : item.goal_id
              ? () => router.push({ pathname: '/(main)/goals/[id]', params: { id: item.goal_id as string } })
              : undefined;
        return (
          <View style={styles.row}>
            <View style={styles.rail}>
              <View style={[styles.dot, { backgroundColor: t.bg }]}>
                <Text style={styles.dotEmoji}>{e.emoji}</Text>
              </View>
              {index < items.length - 1 ? <View style={styles.line} /> : null}
            </View>
            <Pressable
              onPress={target}
              disabled={!target}
              accessibilityRole={target ? 'button' : undefined}
              style={({ pressed }) => [styles.entry, pressed && target && styles.entryPressed]}
            >
              <Text style={[type.overline, { color: t.fg }]}>{e.leadText}</Text>
              <Text style={styles.title}>{e.title}</Text>
              <Text style={type.caption}>
                {relativeTime(item.created_at)}
                {target ? ' · view ›' : ''}
              </Text>
            </Pressable>
          </View>
        );
      }}
      ListEmptyComponent={
        <EmptyState
          emoji="🌱"
          title="Nothing here yet"
          body={`As you keep memories and confirm reflections, ${twinName}'s growth shows up here.`}
        />
      }
    />
  );
}

const styles = StyleSheet.create({
  list: { flex: 1, backgroundColor: colors.bg },
  content: { gap: 0 },
  intro: { ...type.body, color: colors.muted, marginBottom: space.lg },
  row: { flexDirection: 'row', gap: space.md },
  rail: { alignItems: 'center', width: 40 },
  dot: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: 'center',
    justifyContent: 'center',
  },
  dotEmoji: { fontSize: 18 },
  line: { flex: 1, width: 2, backgroundColor: colors.border, marginVertical: 4 },
  entry: {
    flex: 1,
    backgroundColor: colors.surface,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.border,
    padding: space.md,
    gap: 2,
    marginBottom: space.md,
  },
  entryPressed: { backgroundColor: colors.surfaceAlt },
  title: { ...type.heading },
});
