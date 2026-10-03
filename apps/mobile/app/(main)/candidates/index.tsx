/**
 * Memory Candidates screen (Sprint 4, DF6).
 *
 * The highest-impact mobile surface: the user approves or rejects what the
 * Twin is proposing to remember. Only pending candidates are shown. Each
 * action is a POST that resolves the candidate server-side; on success the
 * row vanishes locally so the user keeps moving.
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
import { Stack, useRouter } from 'expo-router';

import { api, APIError } from '@/api/client';
import type { MemoryCandidate } from '@/api/types';

export default function CandidatesScreen() {
  const router = useRouter();
  const [items, setItems] = useState<MemoryCandidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    const res = await api.listCandidates('pending');
    setItems(res.items);
  }, []);

  useEffect(() => {
    load()
      .catch((e) => Alert.alert('Could not load candidates', String(e)))
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

  async function confirmOne(id: string) {
    setBusyId(id);
    try {
      await api.confirmCandidate(id);
      setItems((prev) => prev.filter((c) => c.id !== id));
    } catch (e) {
      Alert.alert(
        'Could not confirm',
        e instanceof APIError ? e.message : String(e),
      );
    } finally {
      setBusyId(null);
    }
  }

  async function rejectOne(id: string) {
    setBusyId(id);
    try {
      await api.rejectCandidate(id);
      setItems((prev) => prev.filter((c) => c.id !== id));
    } catch (e) {
      Alert.alert(
        'Could not reject',
        e instanceof APIError ? e.message : String(e),
      );
    } finally {
      setBusyId(null);
    }
  }

  return (
    <View style={styles.container}>
      <Stack.Screen options={{ title: 'Review memories' }} />
      {loading ? (
        <ActivityIndicator style={{ marginTop: 40 }} />
      ) : (
        <FlatList
          data={items}
          keyExtractor={(c) => c.id}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
          }
          renderItem={({ item }) => (
            <View style={styles.card}>
              <View style={styles.cardHeader}>
                <Text style={styles.badge}>{item.type}</Text>
                <Text style={styles.conf}>
                  conf {item.confidence.toFixed(2)} · imp{' '}
                  {item.importance.toFixed(2)}
                </Text>
              </View>
              <Text style={styles.content}>{item.content}</Text>
              <View style={styles.actions}>
                <Pressable
                  disabled={busyId === item.id}
                  onPress={() => rejectOne(item.id)}
                  style={[styles.btn, styles.btnReject]}
                >
                  <Text style={styles.btnRejectText}>Reject</Text>
                </Pressable>
                <Pressable
                  disabled={busyId === item.id}
                  onPress={() => confirmOne(item.id)}
                  style={[styles.btn, styles.btnConfirm]}
                >
                  <Text style={styles.btnConfirmText}>
                    {busyId === item.id ? '…' : 'Keep'}
                  </Text>
                </Pressable>
              </View>
            </View>
          )}
          ListEmptyComponent={
            <View style={styles.empty}>
              <Text style={styles.emptyTitle}>Nothing to review</Text>
              <Text style={styles.emptyBody}>
                As you chat, the Twin will propose memories here for you to
                keep or reject.
              </Text>
              <Pressable
                onPress={() => router.back()}
                style={[styles.btn, styles.btnBack]}
              >
                <Text style={styles.btnConfirmText}>Back</Text>
              </Pressable>
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
    gap: 10,
  },
  cardHeader: { flexDirection: 'row', justifyContent: 'space-between' },
  badge: {
    backgroundColor: '#eef2ff',
    color: '#4338ca',
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 8,
    fontSize: 11,
    fontWeight: '700',
  },
  conf: { color: '#6b7280', fontSize: 12 },
  content: { fontSize: 15, lineHeight: 20, color: '#111827' },
  actions: { flexDirection: 'row', justifyContent: 'flex-end', gap: 8 },
  btn: {
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 10,
  },
  btnConfirm: { backgroundColor: '#4f46e5' },
  btnConfirmText: { color: '#ffffff', fontWeight: '700' },
  btnReject: {
    backgroundColor: '#ffffff',
    borderWidth: 1,
    borderColor: '#d1d5db',
  },
  btnRejectText: { color: '#374151', fontWeight: '600' },
  btnBack: { marginTop: 12, backgroundColor: '#4f46e5' },
  empty: { alignItems: 'center', marginTop: 60, padding: 24 },
  emptyTitle: { fontSize: 18, fontWeight: '700', marginBottom: 6 },
  emptyBody: {
    textAlign: 'center',
    color: '#6b7280',
    fontSize: 14,
    lineHeight: 20,
  },
});
