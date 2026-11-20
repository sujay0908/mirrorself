/**
 * Review: what your Twin would like to remember, waiting for your yes or no.
 *
 * Only pending suggestions are shown. Each answer is a POST that resolves the
 * suggestion server-side; on success the card disappears so you keep moving.
 */

import { useCallback, useEffect, useState } from 'react';
import { FlatList, RefreshControl, StyleSheet, Text, View } from 'react-native';
import { useRouter } from 'expo-router';

import { api, APIError } from '@/api/client';
import type { MemoryCandidate } from '@/api/types';
import { confidenceLabel, importanceLabel, memoryType } from '@/lib/format';
import { goBackOr } from '@/lib/navigation';
import { useRefreshOnFocus } from '@/lib/use-refresh-on-focus';
import { userErrorMessage } from '@/lib/user-errors';
import { useSession } from '@/state/session';
import { Alert } from '@/ui/alert';
import {
  Button,
  ButtonRow,
  Card,
  EmptyState,
  ErrorState,
  listContent,
  Loading,
  Tag,
} from '@/ui/kit';
import { colors, space, type } from '@/ui/theme';

export default function CandidatesScreen() {
  const router = useRouter();
  const twinName = useSession((s) => s.twin?.display_name ?? 'Your Twin');
  const [items, setItems] = useState<MemoryCandidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState<{ id: string; action: 'keep' | 'reject' } | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await api.listCandidates('pending');
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

  const remove = (id: string) => setItems((prev) => prev.filter((c) => c.id !== id));

  async function keep(id: string) {
    setBusy({ id, action: 'keep' });
    try {
      await api.confirmCandidate(id);
      remove(id);
    } catch (e) {
      if (alreadyHandled(e)) {
        // Done already (an earlier attempt that seemed to fail went
        // through). Nothing to tell the person; just clear it.
        remove(id);
        return;
      }
      Alert.alert('Could not keep this', userErrorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  async function reject(id: string) {
    setBusy({ id, action: 'reject' });
    try {
      await api.rejectCandidate(id);
      remove(id);
    } catch (e) {
      if (alreadyHandled(e)) {
        remove(id);
        return;
      }
      Alert.alert('Could not dismiss this', userErrorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  if (loading) return <Loading />;
  if (error && items.length === 0) {
    return (
      <ErrorState
        title="Could not load suggestions"
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
      keyExtractor={(c) => c.id}
      contentContainerStyle={listContent}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
      ListHeaderComponent={
        items.length > 0 ? (
          <Text style={styles.intro}>
            {twinName} noticed these in your chats. Keep what&apos;s right — it only
            remembers what you approve, and you can edit or delete it later.
          </Text>
        ) : null
      }
      renderItem={({ item }) => {
        const t = memoryType(item.type);
        const isBusy = busy?.id === item.id;
        return (
          <Card style={styles.card}>
            <Tag label={`${t.emoji} ${t.label}`} tone={t.tone} />
            <Text style={styles.content}>{item.content}</Text>
            <Text style={type.caption}>
              {confidenceLabel(item.confidence)} · {importanceLabel(item.importance)}
            </Text>
            <ButtonRow>
              <Button
                title="Not right"
                variant="secondary"
                onPress={() => reject(item.id)}
                loading={isBusy && busy?.action === 'reject'}
                disabled={isBusy}
              />
              <Button
                title="✓  Keep"
                onPress={() => keep(item.id)}
                loading={isBusy && busy?.action === 'keep'}
                disabled={isBusy}
              />
            </ButtonRow>
          </Card>
        );
      }}
      ListEmptyComponent={
        <EmptyState
          emoji="✅"
          title="All caught up"
          body={`When ${twinName} notices something worth remembering, it'll ask you here first.`}
          action={{ title: 'Back', onPress: () => goBackOr(router) }}
        />
      }
    />
  );
}

const styles = StyleSheet.create({
  list: { flex: 1, backgroundColor: colors.bg },
  intro: { ...type.body, color: colors.muted, marginBottom: space.xs },
  card: { gap: space.md },
  content: { fontSize: 17, lineHeight: 24, color: colors.ink, fontWeight: '500' },
});

function alreadyHandled(err: unknown): boolean {
  return err instanceof APIError && err.code === 'memory_candidate_already_resolved';
}
