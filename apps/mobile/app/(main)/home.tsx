/**
 * Home: shows the twin and a list of past conversations. Tapping one opens
 * chat; a floating action creates a new conversation. Sprint 4 adds quick
 * links into the Memories, Candidates and Goals surfaces.
 */

import { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useRouter } from 'expo-router';

import { api } from '@/api/client';
import type { Conversation } from '@/api/types';
import { useSession } from '@/state/session';

export default function HomeScreen() {
  const router = useRouter();
  const twin = useSession((s) => s.twin);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .listConversations()
      .then((res) => setConversations(res.items))
      .finally(() => setLoading(false));
  }, []);

  async function newConversation() {
    const created = await api.createConversation();
    router.push({
      pathname: '/(main)/chat/[id]',
      params: { id: created.id },
    });
  }

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
      </View>

      {loading ? (
        <ActivityIndicator />
      ) : (
        <FlatList
          data={conversations}
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
      <Pressable style={styles.fab} onPress={newConversation}>
        <Text style={styles.fabText}>+ New chat</Text>
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
  fab: {
    position: 'absolute',
    right: 20,
    bottom: 32,
    backgroundColor: '#4f46e5',
    paddingHorizontal: 20,
    paddingVertical: 12,
    borderRadius: 999,
  },
  fabText: { color: '#ffffff', fontWeight: '600' },
});
