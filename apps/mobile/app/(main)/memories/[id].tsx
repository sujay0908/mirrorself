/**
 * Memory detail screen (Sprint 4, DF4 + DF6).
 *
 * Shows the memory's content with inline edit, delete, and the
 * "Why does my Twin know this?" provenance panel — bounded message
 * snippets linked back to their source conversation + message.
 */

import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';

import { api, APIError } from '@/api/client';
import type { Memory, MemoryProvenance } from '@/api/types';

export default function MemoryDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [memory, setMemory] = useState<Memory | null>(null);
  const [prov, setProv] = useState<MemoryProvenance | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    const [m, p] = await Promise.all([
      api.getMemory(id),
      api.getMemoryProvenance(id).catch(() => null),
    ]);
    setMemory(m);
    setProv(p);
    setDraft(m.content);
  }, [id]);

  useEffect(() => {
    load()
      .catch((e) => Alert.alert('Could not load', String(e)))
      .finally(() => setLoading(false));
  }, [load]);

  async function save() {
    if (!id || !memory) return;
    const trimmed = draft.trim();
    if (!trimmed) {
      Alert.alert('Content cannot be empty.');
      return;
    }
    setSaving(true);
    try {
      const updated = await api.patchMemory(id, { content: trimmed });
      setMemory(updated);
      setEditing(false);
    } catch (e) {
      Alert.alert(
        'Could not save',
        e instanceof APIError ? e.message : String(e),
      );
    } finally {
      setSaving(false);
    }
  }

  function askDelete() {
    Alert.alert('Delete memory?', 'This cannot be undone.', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Delete',
        style: 'destructive',
        onPress: async () => {
          if (!id) return;
          try {
            await api.deleteMemory(id);
            router.back();
          } catch (e) {
            Alert.alert(
              'Could not delete',
              e instanceof APIError ? e.message : String(e),
            );
          }
        },
      },
    ]);
  }

  async function unsupersede() {
    if (!id || !memory) return;
    try {
      const updated = await api.unsupersedeMemory(id);
      setMemory(updated);
    } catch (e) {
      Alert.alert(
        'Could not un-supersede',
        e instanceof APIError ? e.message : String(e),
      );
    }
  }

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator />
      </View>
    );
  }
  if (!memory) {
    return (
      <View style={styles.center}>
        <Text>Memory not found.</Text>
      </View>
    );
  }

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
    >
      <Stack.Screen options={{ title: 'Memory' }} />
      <View style={styles.header}>
        <Text style={styles.badge}>{memory.type}</Text>
        <Text style={styles.date}>
          {new Date(memory.created_at).toLocaleString()}
        </Text>
      </View>

      {memory.superseded_by_memory_id ? (
        <View style={styles.supersededBanner}>
          <Text style={styles.supersededTitle}>Superseded</Text>
          <Text style={styles.supersededBody}>
            Your Twin stopped using this memory for new chats because a
            confirmed reflection marked it as replaced. The row is kept
            here so you can review it, see what replaced it, or restore
            it.
          </Text>
          <View style={styles.row}>
            <Pressable
              onPress={() =>
                router.push({
                  pathname: '/(main)/memories/[id]',
                  params: {
                    id: memory.superseded_by_memory_id as string,
                  },
                })
              }
              style={[styles.btn, styles.btnSecondary]}
            >
              <Text style={styles.btnSecondaryText}>View replacement</Text>
            </Pressable>
            <Pressable
              onPress={unsupersede}
              style={[styles.btn, styles.btnPrimary]}
            >
              <Text style={styles.btnPrimaryText}>Un-supersede</Text>
            </Pressable>
          </View>
        </View>
      ) : null}

      {editing ? (
        <TextInput
          value={draft}
          onChangeText={setDraft}
          multiline
          style={styles.editInput}
        />
      ) : (
        <Text style={styles.body}>{memory.content}</Text>
      )}

      <View style={styles.row}>
        {editing ? (
          <>
            <Pressable
              onPress={() => {
                setDraft(memory.content);
                setEditing(false);
              }}
              style={[styles.btn, styles.btnSecondary]}
            >
              <Text style={styles.btnSecondaryText}>Cancel</Text>
            </Pressable>
            <Pressable
              onPress={save}
              disabled={saving}
              style={[styles.btn, styles.btnPrimary]}
            >
              <Text style={styles.btnPrimaryText}>
                {saving ? '…' : 'Save'}
              </Text>
            </Pressable>
          </>
        ) : (
          <>
            <Pressable
              onPress={askDelete}
              style={[styles.btn, styles.btnDanger]}
            >
              <Text style={styles.btnDangerText}>Delete</Text>
            </Pressable>
            <Pressable
              onPress={() => setEditing(true)}
              style={[styles.btn, styles.btnPrimary]}
            >
              <Text style={styles.btnPrimaryText}>Edit</Text>
            </Pressable>
          </>
        )}
      </View>

      <Text style={styles.sectionTitle}>Why does my Twin know this?</Text>
      {prov && prov.sources.length > 0 ? (
        prov.sources.map((s) => (
          <View key={s.source_id} style={styles.sourceCard}>
            <Text style={styles.sourceType}>
              {s.source_type}
              {s.source_snippet_truncated ? ' · snippet' : ''}
            </Text>
            {s.source_snippet ? (
              <Text style={styles.sourceSnippet}>“{s.source_snippet}”</Text>
            ) : (
              <Text style={styles.sourceGone}>
                Source message no longer available.
              </Text>
            )}
            <Text style={styles.sourceMeta}>
              {new Date(s.created_at).toLocaleString()}
            </Text>
            {s.source_conversation_id ? (
              <Pressable
                onPress={() =>
                  router.push({
                    pathname: '/(main)/chat/[id]',
                    params: { id: s.source_conversation_id as string },
                  })
                }
              >
                <Text style={styles.sourceLink}>Open conversation →</Text>
              </Pressable>
            ) : null}
          </View>
        ))
      ) : (
        <Text style={styles.emptyBody}>No sources recorded.</Text>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#f9fafb' },
  content: { padding: 16, gap: 12 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  badge: {
    backgroundColor: '#eef2ff',
    color: '#4338ca',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 999,
    fontSize: 12,
    fontWeight: '700',
  },
  date: { color: '#6b7280', fontSize: 12 },
  body: {
    fontSize: 16,
    lineHeight: 24,
    color: '#111827',
    backgroundColor: '#ffffff',
    padding: 14,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#e5e7eb',
  },
  editInput: {
    fontSize: 16,
    lineHeight: 24,
    color: '#111827',
    backgroundColor: '#ffffff',
    padding: 14,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#4f46e5',
    minHeight: 100,
  },
  row: { flexDirection: 'row', justifyContent: 'flex-end', gap: 8 },
  btn: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 10 },
  btnPrimary: { backgroundColor: '#4f46e5' },
  btnPrimaryText: { color: '#ffffff', fontWeight: '700' },
  btnSecondary: {
    backgroundColor: '#ffffff',
    borderWidth: 1,
    borderColor: '#d1d5db',
  },
  btnSecondaryText: { color: '#374151', fontWeight: '600' },
  btnDanger: {
    backgroundColor: '#ffffff',
    borderWidth: 1,
    borderColor: '#fecaca',
  },
  btnDangerText: { color: '#b91c1c', fontWeight: '600' },
  sectionTitle: {
    marginTop: 20,
    fontSize: 15,
    fontWeight: '700',
    color: '#111827',
  },
  sourceCard: {
    backgroundColor: '#ffffff',
    padding: 12,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#e5e7eb',
    gap: 6,
  },
  sourceType: { fontSize: 12, color: '#6b7280', fontWeight: '600' },
  sourceSnippet: { fontSize: 14, color: '#111827', fontStyle: 'italic' },
  sourceGone: { fontSize: 13, color: '#9ca3af' },
  sourceMeta: { fontSize: 12, color: '#6b7280' },
  sourceLink: { color: '#4338ca', fontWeight: '600', marginTop: 4 },
  emptyBody: { color: '#6b7280' },
  supersededBanner: {
    backgroundColor: '#fef3c7',
    padding: 14,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#f59e0b',
    gap: 10,
  },
  supersededTitle: { fontSize: 14, fontWeight: '700', color: '#92400e' },
  supersededBody: { fontSize: 13, color: '#78350f', lineHeight: 18 },
});
