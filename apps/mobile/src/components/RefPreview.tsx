/**
 * A memory or goal shown by its words, not its id.
 *
 * Chat citations and reflections only carry ids. Showing "76174ae4…" tells a
 * person nothing, so these rows fetch the item and show what it says; tapping
 * opens it. A deleted item shows as unavailable instead of failing.
 */

import { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useRouter } from 'expo-router';

import { api } from '@/api/client';
import { goalStatus, memoryType } from '@/lib/format';
import { colors, radius, space } from '@/ui/theme';

type State = { status: 'loading' } | { status: 'ready'; text: string; emoji: string } | { status: 'gone' };

export function MemoryPreview({ id }: { id: string }) {
  const router = useRouter();
  const [state, setState] = useState<State>({ status: 'loading' });

  useEffect(() => {
    let cancelled = false;
    api
      .getMemory(id)
      .then((m) => {
        if (!cancelled) setState({ status: 'ready', text: m.content, emoji: memoryType(m.type).emoji });
      })
      .catch(() => {
        if (!cancelled) setState({ status: 'gone' });
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  return (
    <PreviewRow
      state={state}
      fallbackEmoji="🧠"
      goneText="This memory is no longer available."
      onPress={() => router.push({ pathname: '/(main)/memories/[id]', params: { id } })}
    />
  );
}

export function GoalPreview({ id }: { id: string }) {
  const router = useRouter();
  const [state, setState] = useState<State>({ status: 'loading' });

  useEffect(() => {
    let cancelled = false;
    api
      .getGoal(id)
      .then((g) => {
        if (!cancelled) {
          setState({
            status: 'ready',
            text: g.title,
            emoji: g.status === 'active' ? '🎯' : goalStatus(g.status).emoji,
          });
        }
      })
      .catch(() => {
        if (!cancelled) setState({ status: 'gone' });
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  return (
    <PreviewRow
      state={state}
      fallbackEmoji="🎯"
      goneText="This goal is no longer available."
      onPress={() => router.push({ pathname: '/(main)/goals/[id]', params: { id } })}
    />
  );
}

function PreviewRow({
  state,
  fallbackEmoji,
  goneText,
  onPress,
}: {
  state: State;
  fallbackEmoji: string;
  goneText: string;
  onPress: () => void;
}) {
  const gone = state.status === 'gone';
  return (
    <Pressable
      onPress={gone ? undefined : onPress}
      disabled={gone}
      accessibilityRole="button"
      style={({ pressed }) => [styles.row, pressed && styles.rowPressed]}
    >
      <Text style={styles.emoji}>{state.status === 'ready' ? state.emoji : fallbackEmoji}</Text>
      <View style={styles.textWrap}>
        <Text style={[styles.text, gone && styles.gone]} numberOfLines={2}>
          {state.status === 'ready' ? state.text : gone ? goneText : 'Loading…'}
        </Text>
      </View>
      {gone ? null : <Text style={styles.chevron}>›</Text>}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.sm,
    paddingVertical: space.sm,
    paddingHorizontal: space.md,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceAlt,
    borderWidth: 1,
    borderColor: colors.border,
  },
  rowPressed: { backgroundColor: colors.primarySoft },
  emoji: { fontSize: 16 },
  textWrap: { flex: 1 },
  text: { fontSize: 14, lineHeight: 19, color: colors.ink },
  gone: { color: colors.faint, fontStyle: 'italic' },
  chevron: { fontSize: 20, color: colors.faint, marginTop: -2 },
});
