/**
 * Home: shows the twin and a list of past conversations. Tapping one opens
 * chat; a floating action creates a new conversation. Sprint 4 adds quick
 * links into the Memories, Candidates and Goals surfaces.
 */

import { useCallback, useEffect, useReducer, useState } from 'react';
import {
  ActivityIndicator,
  Button,
  FlatList,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useRouter } from 'expo-router';

import { api } from '@/api/client';
import { apiFailureMessage, logApiFailure, type ApiFailure } from '@/api/diagnostics';
import { config } from '@/config';
import {
  CONVERSATIONS_INITIAL,
  conversationListReducer,
} from '@/state/conversation-list';
import { useSession } from '@/state/session';

export default function HomeScreen() {
  const router = useRouter();
  const twin = useSession((s) => s.twin);
  const [state, dispatch] = useReducer(
    conversationListReducer,
    CONVERSATIONS_INITIAL,
  );
  // Bumped by the retry button; re-runs the effect without duplicating it.
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [creating, setCreating] = useState(false);
  const [createFailure, setCreateFailure] = useState<ApiFailure | null>(null);

  useEffect(() => {
    // `cancelled` keeps a slow response from a previous attempt from
    // overwriting the state of the current one after a retry.
    let cancelled = false;
    dispatch({ type: 'load' });
    api
      .listConversations()
      .then((res) => {
        if (!cancelled) dispatch({ type: 'loaded', items: res.items });
      })
      .catch((err: unknown) => {
        // An explicit rejection handler, not `.finally`: `.finally` re-throws,
        // which surfaced as an unhandled promise rejection and left the list
        // silently empty whenever the API was unreachable or rejected the
        // session.
        if (!cancelled) {
          dispatch({
            type: 'failed',
            failure: logApiFailure('GET /v1/conversations', err),
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [loadAttempt]);

  const retry = useCallback(() => setLoadAttempt((n) => n + 1), []);

  // Not an async onPress handler: a rejected createConversation() there is
  // unhandled for exactly the same reason.
  const newConversation = useCallback(() => {
    if (creating) return;
    setCreating(true);
    setCreateFailure(null);
    api
      .createConversation()
      .then((created) => {
        router.push({
          pathname: '/(main)/chat/[id]',
          params: { id: created.id },
        });
      })
      .catch((err: unknown) => {
        setCreateFailure(logApiFailure('POST /v1/conversations', err));
      })
      .finally(() => setCreating(false));
  }, [creating, router]);

  return (
    <View style={styles.container}>
      <Text style={styles.title}>{twin?.display_name ?? 'Your Twin'}</Text>
      <Text style={styles.subtitle}>
        Style: {twin?.profile.communication_style_preset ?? 'neutral'}
      </Text>

      <View style={styles.tiles}>
        <Pressable
          style={styles.tile}
          onPress={() => router.push('/(main)/goals')}
        >
          <Text style={styles.tileTitle}>Goals</Text>
          <Text style={styles.tileSub}>What you&apos;re pursuing</Text>
        </Pressable>
        <Pressable
          style={styles.tile}
          onPress={() => router.push('/(main)/memories')}
        >
          <Text style={styles.tileTitle}>Memories</Text>
          <Text style={styles.tileSub}>What your Twin remembers</Text>
        </Pressable>
        <Pressable
          style={styles.tile}
          onPress={() => router.push('/(main)/candidates')}
        >
          <Text style={styles.tileTitle}>Review</Text>
          <Text style={styles.tileSub}>Pending memory candidates</Text>
        </Pressable>
        <Pressable
          style={styles.tile}
          onPress={() => router.push('/(main)/reflections')}
        >
          <Text style={styles.tileTitle}>Reflections</Text>
          <Text style={styles.tileSub}>What your Twin noticed</Text>
        </Pressable>
        <Pressable
          style={styles.tile}
          onPress={() => router.push('/(main)/evolution')}
        >
          <Text style={styles.tileTitle}>Evolution</Text>
          <Text style={styles.tileSub}>What your Twin learned</Text>
        </Pressable>
        <Pressable
          style={styles.tile}
          onPress={() => router.push('/(main)/portrait')}
        >
          <Text style={styles.tileTitle}>Self-portrait</Text>
          <Text style={styles.tileSub}>See what your Twin knows about you.</Text>
        </Pressable>
      </View>

      {state.status === 'loading' ? (
        <ActivityIndicator />
      ) : state.status === 'failed' ? (
        <View style={styles.error}>
          <Text style={styles.errorTitle}>Could not load your conversations</Text>
          <Text style={styles.errorBody}>
            {apiFailureMessage(state.failure, config.apiUrl)}
          </Text>
          <Button title="Try again" onPress={retry} />
        </View>
      ) : (
        <FlatList
          data={state.items}
          keyExtractor={(c) => c.id}
          renderItem={({ item }) => (
            <Pressable
              onPress={() =>
                router.push({
                  pathname: '/(main)/chat/[id]',
                  params: { id: item.id },
                })
              }
              style={styles.row}
            >
              <Text style={styles.rowTitle}>
                {item.title ?? 'Untitled conversation'}
              </Text>
              <Text style={styles.rowMeta}>
                {new Date(item.updated_at).toLocaleString()}
              </Text>
            </Pressable>
          )}
          ListEmptyComponent={
            <Text style={styles.empty}>No conversations yet.</Text>
          }
        />
      )}
      {createFailure ? (
        <Text style={styles.createError}>
          {apiFailureMessage(createFailure, config.apiUrl)}
        </Text>
      ) : null}
      <Pressable
        style={[styles.fab, creating ? styles.fabDisabled : null]}
        onPress={newConversation}
        disabled={creating}
      >
        <Text style={styles.fabText}>
          {creating ? 'Starting…' : '+ New chat'}
        </Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 16, gap: 8 },
  title: { fontSize: 24, fontWeight: '700' },
  subtitle: { fontSize: 14, color: '#4b5563', marginBottom: 8 },
  tiles: {
    flexDirection: 'row',
    gap: 8,
    marginBottom: 16,
  },
  tile: {
    flex: 1,
    backgroundColor: '#eef2ff',
    padding: 12,
    borderRadius: 12,
    minHeight: 72,
  },
  tileTitle: { fontSize: 14, fontWeight: '700', color: '#312e81' },
  tileSub: { fontSize: 11, color: '#4338ca', marginTop: 4 },
  row: {
    padding: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#e5e7eb',
  },
  rowTitle: { fontSize: 16, fontWeight: '600' },
  rowMeta: { fontSize: 12, color: '#6b7280' },
  empty: { textAlign: 'center', marginTop: 40, color: '#6b7280' },
  error: { marginTop: 32, paddingHorizontal: 8, gap: 8 },
  errorTitle: { fontSize: 16, fontWeight: '700', textAlign: 'center' },
  errorBody: { fontSize: 13, color: '#4b5563', textAlign: 'center' },
  createError: {
    position: 'absolute',
    left: 20,
    right: 20,
    bottom: 80,
    fontSize: 12,
    color: '#b91c1c',
    textAlign: 'right',
  },
  fab: {
    position: 'absolute',
    right: 20,
    bottom: 32,
    backgroundColor: '#4f46e5',
    paddingHorizontal: 20,
    paddingVertical: 12,
    borderRadius: 999,
  },
  fabDisabled: { backgroundColor: '#a5b4fc' },
  fabText: { color: '#ffffff', fontWeight: '600' },
});
