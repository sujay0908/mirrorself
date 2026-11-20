/**
 * Self-portrait: what your Twin knows about you, in one place.
 *
 * Four sections composed server-side from data you already approved — no AI
 * involved, nothing changes by opening it. "Your Twin learned…" vs "You
 * acknowledged…" wording follows the same rule as the Evolution screen.
 */

import { useCallback, useEffect, useState } from 'react';
import { Pressable, RefreshControl, StyleSheet, Text, View } from 'react-native';
import { useRouter } from 'expo-router';

import { api } from '@/api/client';
import type { TwinPortrait } from '@/api/types';
import {
  friendlyEvent,
  humanizeKey,
  importanceLabel,
  memoryType,
  priorityLabel,
  relativeTime,
  shortDate,
  styleInfo,
} from '@/lib/format';
import { useRefreshOnFocus } from '@/lib/use-refresh-on-focus';
import { userErrorMessage } from '@/lib/user-errors';
import {
  Avatar,
  Button,
  Card,
  Centered,
  ErrorState,
  Loading,
  Page,
  SectionTitle,
  Tag,
} from '@/ui/kit';
import { colors, radius, space, tones, type } from '@/ui/theme';

const TYPE_ORDER = ['FACT', 'PREFERENCE', 'EXPERIENCE', 'GOAL'];

export default function PortraitScreen() {
  const router = useRouter();
  const [portrait, setPortrait] = useState<TwinPortrait | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setPortrait(await api.getTwinPortrait());
      setError(null);
    } catch (e) {
      setError(userErrorMessage(e));
    }
  }, []);

  useEffect(() => {
    load().finally(() => setLoading(false));
  }, [load]);

  // The profile, memories and goals it summarises are edited elsewhere.
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
  if (!portrait) {
    return (
      <Centered>
        <ErrorState
          title="Could not load your portrait"
          message={error ?? 'Please try again.'}
          onRetry={() => {
            setLoading(true);
            load().finally(() => setLoading(false));
          }}
        />
      </Centered>
    );
  }

  const { profile, memory_summary: mem, active_goals: goals, recent_evolution: recent } = portrait;
  const style = styleInfo(profile.style_preset);
  const basics = Object.entries(profile.basic_profile ?? {});
  const counts = TYPE_ORDER.map((t) => ({ type: t, count: mem.counts_by_type[t] ?? 0 }));

  return (
    <Page refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}>
      <View style={styles.hero}>
        <Avatar name={profile.display_name} size={64} />
        <Text style={type.title}>{profile.display_name}</Text>
        <Text style={styles.heroLead}>Here&apos;s what I know about you so far.</Text>
      </View>

      <SectionTitle action={{ title: 'Edit', onPress: () => router.push('/(main)/profile') }}>
        How I talk to you
      </SectionTitle>
      <Card>
        <View style={styles.styleRow}>
          <Text style={styles.styleEmoji}>{style.emoji}</Text>
          <View style={styles.flex}>
            <Text style={type.heading}>{style.label}</Text>
            <Text style={type.small}>{style.description}</Text>
          </View>
        </View>
        {profile.style_notes ? (
          <View style={styles.quote}>
            <Text style={styles.quoteText}>“{profile.style_notes}”</Text>
          </View>
        ) : null}
        {basics.length > 0 ? (
          <View style={styles.basics}>
            {basics.map(([k, v]) => (
              <View key={k} style={styles.basicRow}>
                <Text style={styles.basicKey}>{humanizeKey(k)}</Text>
                <Text style={styles.basicValue}>{String(v)}</Text>
              </View>
            ))}
          </View>
        ) : (
          <Text style={type.small}>
            Add a few basics — where you live, what you do — so I don&apos;t have to ask.
          </Text>
        )}
      </Card>

      <SectionTitle action={{ title: 'All memories', onPress: () => router.push('/(main)/memories') }}>
        What I remember
      </SectionTitle>
      <Card>
        <View style={styles.counts}>
          {counts.map(({ type: t, count }) => {
            const info = memoryType(t);
            return (
              <View key={t} style={[styles.countTile, { backgroundColor: tones[info.tone].bg }]}>
                <Text style={styles.countEmoji}>{info.emoji}</Text>
                <Text style={[styles.countNum, { color: tones[info.tone].fg }]}>{count}</Text>
                <Text style={type.caption}>{info.plural}</Text>
              </View>
            );
          })}
        </View>
        {mem.top_memories.length > 0 ? (
          <View style={styles.rows}>
            <Text style={type.overline}>Most important</Text>
            {mem.top_memories.map((m) => {
              const info = memoryType(m.type);
              return (
                <Pressable
                  key={m.id}
                  onPress={() => router.push({ pathname: '/(main)/memories/[id]', params: { id: m.id } })}
                  accessibilityRole="button"
                  style={({ pressed }) => [styles.itemRow, pressed && styles.itemRowPressed]}
                >
                  <Text style={styles.itemEmoji}>{info.emoji}</Text>
                  <View style={styles.flex}>
                    <Text style={styles.itemText} numberOfLines={2}>
                      {m.snippet}
                    </Text>
                    <Text style={type.caption}>{importanceLabel(m.importance)}</Text>
                  </View>
                  <Text style={styles.chevron}>›</Text>
                </Pressable>
              );
            })}
          </View>
        ) : (
          <Text style={type.small}>
            Nothing yet. As you keep the memories I suggest, they&apos;ll show up here.
          </Text>
        )}
      </Card>

      <SectionTitle action={{ title: 'All goals', onPress: () => router.push('/(main)/goals') }}>
        What you&apos;re working on
      </SectionTitle>
      <Card>
        {goals.length === 0 ? (
          <Text style={type.small}>No active goals. Add one so I can keep it in mind.</Text>
        ) : (
          goals.map((g) => (
            <Pressable
              key={g.id}
              onPress={() => router.push({ pathname: '/(main)/goals/[id]', params: { id: g.id } })}
              accessibilityRole="button"
              style={({ pressed }) => [styles.itemRow, pressed && styles.itemRowPressed]}
            >
              <Text style={styles.itemEmoji}>🎯</Text>
              <View style={styles.flex}>
                <Text style={styles.itemText} numberOfLines={2}>
                  {g.title}
                </Text>
                <Text style={type.caption}>
                  {priorityLabel(g.priority)} priority
                  {g.target_date ? ` · by ${shortDate(g.target_date)}` : ''}
                </Text>
              </View>
              <Text style={styles.chevron}>›</Text>
            </Pressable>
          ))
        )}
      </Card>

      <SectionTitle action={{ title: 'Full history', onPress: () => router.push('/(main)/evolution') }}>
        Recently
      </SectionTitle>
      <Card>
        {recent.length === 0 ? (
          <Text style={type.small}>
            As you keep memories and confirm reflections, changes show up here.
          </Text>
        ) : (
          recent.map((r) => {
            const e = friendlyEvent(r.event_type, r.summary);
            return (
              <View key={r.id} style={styles.itemRow}>
                <Text style={styles.itemEmoji}>{e.emoji}</Text>
                <View style={styles.flex}>
                  <Text style={styles.itemText}>{e.title}</Text>
                  <Text style={type.caption}>
                    {e.leadText} · {relativeTime(r.created_at)}
                  </Text>
                </View>
              </View>
            );
          })
        )}
      </Card>

      <Button
        title="Edit profile"
        variant="secondary"
        onPress={() => router.push('/(main)/profile')}
        style={styles.footerButton}
      />
      {error ? <Tag label="Showing the last version we loaded" tone="warning" /> : null}
    </Page>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  hero: { alignItems: 'center', gap: space.xs, paddingVertical: space.md },
  heroLead: { ...type.body, color: colors.muted },
  styleRow: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  styleEmoji: { fontSize: 28 },
  quote: {
    borderLeftWidth: 3,
    borderLeftColor: colors.primary,
    backgroundColor: colors.surfaceAlt,
    borderRadius: radius.sm,
    paddingVertical: space.sm,
    paddingHorizontal: space.md,
  },
  quoteText: { ...type.body, color: colors.ink, fontStyle: 'italic' },
  basics: { gap: 6 },
  basicRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: space.md,
    paddingVertical: 6,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  basicKey: { ...type.small },
  basicValue: { ...type.bodyStrong, flexShrink: 1, textAlign: 'right' },
  counts: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm },
  countTile: {
    flexGrow: 1,
    flexBasis: 70,
    borderRadius: radius.md,
    paddingVertical: space.md,
    alignItems: 'center',
    gap: 2,
  },
  countEmoji: { fontSize: 18 },
  countNum: { fontSize: 22, fontWeight: '800' },
  rows: { gap: 4, marginTop: space.sm },
  itemRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
    paddingVertical: space.sm,
    paddingHorizontal: space.xs,
    borderRadius: radius.sm,
  },
  itemRowPressed: { backgroundColor: colors.surfaceAlt },
  itemEmoji: { fontSize: 18, width: 26, textAlign: 'center' },
  itemText: { ...type.body, color: colors.ink },
  chevron: { fontSize: 22, color: colors.faint },
  footerButton: { marginTop: space.md, alignSelf: 'center' },
});
