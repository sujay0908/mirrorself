/**
 * Reflections: things your Twin noticed by looking across your memories,
 * goals and recent chats.
 *
 * The Twin proposes; you decide; only your confirmation changes anything.
 * Four kinds: a profile suggestion, two memories that say the same thing, a
 * note for a goal, and an insight.
 *
 * Product rules kept from the original screen:
 *   • Confirming an INSIGHT is acknowledgement only — no memory is created
 *     and the profile does not change — so its button says "Got it".
 *   • A PROFILE suggestion shows the current and proposed values and the
 *     reason BEFORE you confirm.
 */

import { useCallback, useEffect, useState } from 'react';
import { FlatList, Pressable, RefreshControl, StyleSheet, Text, View } from 'react-native';
import { Stack } from 'expo-router';

import { api, APIError } from '@/api/client';
import type {
  GoalUpdatePayload,
  InsightPayload,
  MemoryDedupPayload,
  ProfileUpdatePayload,
  Reflection,
  ReflectionPayload,
} from '@/api/types';
import { GoalPreview, MemoryPreview } from '@/components/RefPreview';
import {
  formatProfileValue,
  plural,
  profileFieldLabel,
  reflectionKind,
  reflectionRunMessage,
} from '@/lib/format';
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
import { colors, radius, space, type } from '@/ui/theme';

function Why({ text }: { text: string }) {
  if (!text) return null;
  return (
    <View style={styles.why}>
      <Text style={type.overline}>Why</Text>
      <Text style={styles.whyText}>{text}</Text>
    </View>
  );
}

function ProfileUpdateBody({ payload }: { payload: ProfileUpdatePayload }) {
  return (
    <View style={styles.body}>
      <Text style={type.bodyStrong}>Update “{profileFieldLabel(payload.field)}”</Text>
      <View style={styles.diff}>
        <View style={[styles.diffBox, styles.diffBefore]}>
          <Text style={type.overline}>Now</Text>
          <Text style={styles.diffText}>{formatProfileValue(payload.current_value)}</Text>
        </View>
        <View style={[styles.diffBox, styles.diffAfter]}>
          <Text style={[type.overline, { color: colors.success }]}>Suggested</Text>
          <Text style={styles.diffText}>{formatProfileValue(payload.proposed_value)}</Text>
        </View>
      </View>
      <Why text={payload.rationale} />
    </View>
  );
}

function MemoryDedupBody({ payload }: { payload: MemoryDedupPayload }) {
  return (
    <View style={styles.body}>
      <Text style={type.bodyStrong}>These two memories seem to say the same thing.</Text>
      <Text style={type.caption}>Keep using this one</Text>
      <MemoryPreview id={payload.canonical_memory_id} />
      <Text style={type.caption}>Set this one aside (you can restore it later)</Text>
      <MemoryPreview id={payload.superseded_memory_id} />
      <Why text={payload.rationale} />
    </View>
  );
}

function GoalUpdateBody({ payload }: { payload: GoalUpdatePayload }) {
  return (
    <View style={styles.body}>
      <Text style={type.bodyStrong}>Add a note to this goal</Text>
      <GoalPreview id={payload.goal_id} />
      <View style={[styles.diffBox, styles.diffAfter]}>
        <Text style={styles.diffText}>{payload.note}</Text>
      </View>
      <Text style={type.caption}>The goal itself — title, status, priority — stays as it is.</Text>
      <Why text={payload.rationale} />
    </View>
  );
}

function InsightBody({ payload }: { payload: InsightPayload }) {
  return (
    <View style={styles.body}>
      <Text style={styles.insightHeadline}>{payload.headline}</Text>
      <Text style={type.body}>{payload.body}</Text>
      <Why text={payload.rationale} />
      <Text style={type.caption}>
        Saying “Got it” just notes that you&apos;ve seen this. It doesn&apos;t change
        what your Twin remembers.
      </Text>
    </View>
  );
}

function PayloadBody({ payload }: { payload: ReflectionPayload }) {
  switch (payload.kind) {
    case 'profile_update':
      return <ProfileUpdateBody payload={payload} />;
    case 'memory_dedup':
      return <MemoryDedupBody payload={payload} />;
    case 'goal_update':
      return <GoalUpdateBody payload={payload} />;
    case 'insight':
      return <InsightBody payload={payload} />;
  }
}

function Sources({ item }: { item: Reflection }) {
  const [open, setOpen] = useState(false);
  const total = item.source_memory_ids.length + item.source_goal_ids.length;
  // Dedup and goal notes already show the items they are about.
  if (!total || item.kind === 'memory_dedup') return null;
  const label = [
    item.source_memory_ids.length
      ? plural(item.source_memory_ids.length, 'memory', 'memories')
      : null,
    item.source_goal_ids.length ? plural(item.source_goal_ids.length, 'goal') : null,
  ]
    .filter(Boolean)
    .join(' and ');
  return (
    <View style={styles.sources}>
      <Pressable
        onPress={() => setOpen((v) => !v)}
        accessibilityRole="button"
        accessibilityState={{ expanded: open }}
        hitSlop={6}
      >
        <Text style={styles.sourcesToggle}>
          Based on {label} {open ? '▴' : '▾'}
        </Text>
      </Pressable>
      {open ? (
        <View style={styles.sourceList}>
          {item.source_memory_ids.map((id) => (
            <MemoryPreview key={id} id={id} />
          ))}
          {item.source_goal_ids.map((id) => (
            <GoalPreview key={id} id={id} />
          ))}
        </View>
      ) : null}
    </View>
  );
}

export default function ReflectionsScreen() {
  const twinName = useSession((s) => s.twin?.display_name ?? 'Your Twin');
  const [items, setItems] = useState<Reflection[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [running, setRunning] = useState(false);
  const [busy, setBusy] = useState<{ id: string; action: 'confirm' | 'reject' } | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await api.listReflections('pending');
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

  const reflectNow = useCallback(async () => {
    setRunning(true);
    try {
      const out = await api.runReflections();
      const msg = reflectionRunMessage(out);
      await load();
      Alert.alert(msg.title, msg.body);
    } catch (e) {
      Alert.alert('Could not reflect right now', userErrorMessage(e));
    } finally {
      setRunning(false);
    }
  }, [load]);

  const remove = (id: string) => setItems((prev) => prev.filter((c) => c.id !== id));

  async function confirmOne(id: string) {
    setBusy({ id, action: 'confirm' });
    try {
      const out = await api.confirmReflection(id);
      if (!out.applied) {
        Alert.alert(
          'Saved, but not applied',
          'Your answer was recorded, but the change could not be made. The items it refers to may have changed since.',
        );
      }
      remove(id);
    } catch (e) {
      if (alreadyHandled(e)) {
        remove(id);
        return;
      }
      Alert.alert('Could not confirm', userErrorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  async function rejectOne(id: string) {
    setBusy({ id, action: 'reject' });
    try {
      await api.rejectReflection(id);
      remove(id);
    } catch (e) {
      if (alreadyHandled(e)) {
        remove(id);
        return;
      }
      Alert.alert('Could not dismiss', userErrorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  const header = (
    <Stack.Screen
      options={{
        headerRight: () => (
          <Pressable
            onPress={reflectNow}
            disabled={running}
            accessibilityRole="button"
            hitSlop={8}
            style={styles.headerBtn}
          >
            <Text style={[styles.headerBtnText, running && { color: colors.faint }]}>
              {running ? 'Reflecting…' : 'Reflect now'}
            </Text>
          </Pressable>
        ),
      }}
    />
  );

  if (loading) {
    return (
      <>
        {header}
        <Loading />
      </>
    );
  }
  if (error && items.length === 0) {
    return (
      <>
        {header}
        <ErrorState
          title="Could not load reflections"
          message={error}
          onRetry={() => {
            setLoading(true);
            load().finally(() => setLoading(false));
          }}
        />
      </>
    );
  }

  return (
    <>
      {header}
      <FlatList
        style={styles.list}
        data={items}
        keyExtractor={(c) => c.id}
        contentContainerStyle={listContent}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
        ListHeaderComponent={
          items.length > 0 ? (
            <Text style={styles.intro}>
              {twinName} looked across your memories, goals and chats. Nothing changes
              unless you confirm it.
            </Text>
          ) : null
        }
        renderItem={({ item }) => {
          const k = reflectionKind(item.kind);
          const isBusy = busy?.id === item.id;
          return (
            <Card style={styles.card}>
              <Tag label={`${k.emoji} ${k.label}`} tone={k.tone} />
              <PayloadBody payload={item.proposed_payload} />
              <Sources item={item} />
              <ButtonRow>
                <Button
                  title={item.kind === 'insight' ? 'Not really' : 'Dismiss'}
                  variant="secondary"
                  onPress={() => rejectOne(item.id)}
                  loading={isBusy && busy?.action === 'reject'}
                  disabled={isBusy}
                />
                <Button
                  title={item.kind === 'insight' ? 'Got it' : 'Confirm'}
                  onPress={() => confirmOne(item.id)}
                  loading={isBusy && busy?.action === 'confirm'}
                  disabled={isBusy}
                />
              </ButtonRow>
            </Card>
          );
        }}
        ListEmptyComponent={
          <EmptyState
            emoji="💡"
            title="Nothing to reflect on yet"
            body={`After a few chats, ask ${twinName} to reflect. It may suggest profile updates, tidy up duplicate memories, or share an insight — and only you can confirm them.`}
            action={{ title: running ? 'Reflecting…' : 'Reflect now', onPress: reflectNow }}
          />
        }
      />
    </>
  );
}

const styles = StyleSheet.create({
  list: { flex: 1, backgroundColor: colors.bg },
  intro: { ...type.body, color: colors.muted, marginBottom: space.xs },
  card: { gap: space.md },
  body: { gap: space.sm },
  diff: { gap: space.sm },
  diffBox: { borderRadius: radius.md, padding: space.md, gap: 4 },
  diffBefore: { backgroundColor: colors.surfaceAlt, borderWidth: 1, borderColor: colors.border },
  diffAfter: { backgroundColor: colors.successSoft },
  diffText: { ...type.body, color: colors.ink },
  why: { gap: 2 },
  whyText: { ...type.body, color: colors.text, fontStyle: 'italic' },
  insightHeadline: { ...type.title, fontSize: 18, lineHeight: 24 },
  sources: { gap: space.sm },
  sourcesToggle: { color: colors.primary, fontWeight: '700', fontSize: 13 },
  sourceList: { gap: 6 },
  headerBtn: { paddingHorizontal: space.md, paddingVertical: 6 },
  headerBtnText: { color: colors.primary, fontWeight: '700', fontSize: 15 },
});

function alreadyHandled(err: unknown): boolean {
  return err instanceof APIError && err.code === 'reflection_already_resolved';
}
