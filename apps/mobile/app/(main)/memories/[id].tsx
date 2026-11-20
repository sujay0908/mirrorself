/**
 * One memory: what it says, edit or delete it, and "Why does my Twin know
 * this?" — the chat messages it came from, linked back to the conversation.
 */

import { useCallback, useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';

import { api } from '@/api/client';
import type { Memory, MemoryProvenance } from '@/api/types';
import { importanceLabel, memoryType, shortDateTime, sourceLabel } from '@/lib/format';
import { goBackOr } from '@/lib/navigation';
import { userErrorMessage } from '@/lib/user-errors';
import { Alert } from '@/ui/alert';
import {
  Button,
  ButtonRow,
  Card,
  Centered,
  ErrorState,
  Loading,
  Notice,
  Page,
  SectionTitle,
  Tag,
  TextField,
} from '@/ui/kit';
import { colors, radius, space, type } from '@/ui/theme';

export default function MemoryDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [memory, setMemory] = useState<Memory | null>(null);
  const [prov, setProv] = useState<MemoryProvenance | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);
  const [restoring, setRestoring] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const [m, p] = await Promise.all([
        api.getMemory(id),
        api.getMemoryProvenance(id).catch(() => null),
      ]);
      setMemory(m);
      setProv(p);
      setDraft(m.content);
      setLoadError(null);
    } catch (e) {
      setLoadError(userErrorMessage(e));
    }
  }, [id]);

  useEffect(() => {
    load().finally(() => setLoading(false));
  }, [load]);

  async function save() {
    if (!id || !memory) return;
    const trimmed = draft.trim();
    if (!trimmed) {
      Alert.alert('A memory cannot be empty.', 'To remove it, use Delete instead.');
      return;
    }
    setSaving(true);
    try {
      const updated = await api.patchMemory(id, { content: trimmed });
      setMemory(updated);
      setEditing(false);
    } catch (e) {
      Alert.alert('Could not save', userErrorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  function askDelete() {
    Alert.alert('Delete this memory?', 'Your Twin will forget it. This cannot be undone.', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Delete',
        style: 'destructive',
        onPress: async () => {
          if (!id) return;
          try {
            await api.deleteMemory(id);
            goBackOr(router);
          } catch (e) {
            Alert.alert('Could not delete', userErrorMessage(e));
          }
        },
      },
    ]);
  }

  async function restore() {
    if (!id || !memory) return;
    setRestoring(true);
    try {
      const updated = await api.unsupersedeMemory(id);
      setMemory(updated);
    } catch (e) {
      Alert.alert('Could not restore', userErrorMessage(e));
    } finally {
      setRestoring(false);
    }
  }

  if (loading) return <Loading />;
  if (!memory) {
    return (
      <Centered>
        <ErrorState
          title="Could not open this memory"
          message={loadError ?? 'It may have been deleted.'}
          onRetry={() => {
            setLoading(true);
            load().finally(() => setLoading(false));
          }}
        />
      </Centered>
    );
  }

  const t = memoryType(memory.type);

  return (
    <Page>
      {memory.superseded_by_memory_id ? (
        <Notice
          tone="warning"
          title="Replaced by a newer memory"
          body="Your Twin no longer uses this one in chats. You can look at what replaced it, or restore this one."
        >
          <ButtonRow align="start">
            <Button
              title="View replacement"
              variant="secondary"
              size="sm"
              onPress={() =>
                router.push({
                  pathname: '/(main)/memories/[id]',
                  params: { id: memory.superseded_by_memory_id as string },
                })
              }
            />
            <Button title="Restore" size="sm" onPress={restore} loading={restoring} />
          </ButtonRow>
        </Notice>
      ) : null}

      <Card style={styles.card}>
        <View style={styles.metaRow}>
          <Tag label={`${t.emoji} ${t.label}`} tone={t.tone} />
          <Text style={type.caption}>{importanceLabel(memory.importance)}</Text>
        </View>

        {editing ? (
          <TextField value={draft} onChangeText={setDraft} multiline autoFocus />
        ) : (
          <Text style={styles.body} selectable>
            {memory.content}
          </Text>
        )}

        <Text style={type.caption}>Remembered {shortDateTime(memory.created_at)}</Text>

        <ButtonRow>
          {editing ? (
            <>
              <Button
                title="Cancel"
                variant="secondary"
                onPress={() => {
                  setDraft(memory.content);
                  setEditing(false);
                }}
              />
              <Button title="Save" onPress={save} loading={saving} />
            </>
          ) : (
            <>
              <Button title="Delete" variant="danger" onPress={askDelete} />
              <Button title="Edit" variant="secondary" onPress={() => setEditing(true)} />
            </>
          )}
        </ButtonRow>
      </Card>

      <SectionTitle>Why your Twin knows this</SectionTitle>
      {prov && prov.sources.length > 0 ? (
        prov.sources.map((s) => (
          <Card key={s.source_id}>
            <Text style={type.caption}>
              {sourceLabel(s.source_type)} · {shortDateTime(s.created_at)}
            </Text>
            {s.source_snippet ? (
              <View style={styles.quote}>
                <Text style={styles.quoteText}>
                  “{s.source_snippet}
                  {s.source_snippet_truncated ? '…' : ''}”
                </Text>
              </View>
            ) : (
              <Text style={styles.gone}>The original message is no longer available.</Text>
            )}
            {s.source_conversation_id ? (
              <Pressable
                onPress={() =>
                  router.push({
                    pathname: '/(main)/chat/[id]',
                    params: { id: s.source_conversation_id as string },
                  })
                }
                accessibilityRole="link"
                hitSlop={6}
              >
                <Text style={styles.link}>Open the conversation ›</Text>
              </Pressable>
            ) : null}
          </Card>
        ))
      ) : (
        <Text style={type.small}>
          No source recorded — this was added or edited directly.
        </Text>
      )}
    </Page>
  );
}

const styles = StyleSheet.create({
  card: { padding: space.xl, gap: space.md },
  metaRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  body: { fontSize: 19, lineHeight: 28, color: colors.ink, fontWeight: '500' },
  quote: {
    borderLeftWidth: 3,
    borderLeftColor: colors.primary,
    backgroundColor: colors.surfaceAlt,
    borderRadius: radius.sm,
    paddingVertical: space.sm,
    paddingHorizontal: space.md,
  },
  quoteText: { ...type.body, color: colors.ink, fontStyle: 'italic' },
  gone: { ...type.small, fontStyle: 'italic' },
  link: { color: colors.primary, fontWeight: '700', fontSize: 14 },
});
