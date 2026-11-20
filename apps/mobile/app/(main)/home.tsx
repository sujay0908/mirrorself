/**
 * Home: the Twin, a way to start talking, what needs your attention, the
 * places to look after what your Twin knows, and recent conversations.
 */

import { useCallback, useEffect, useReducer, useState } from 'react';
import { FlatList, Pressable, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { useRouter, type Href } from 'expo-router';

import { api } from '@/api/client';
import { apiFailureMessage, logApiFailure, type ApiFailure } from '@/api/diagnostics';
import { supabase } from '@/auth/supabase';
import { config } from '@/config';
import { greeting, plural, relativeTime, styleInfo } from '@/lib/format';
import { useRefreshOnFocus } from '@/lib/use-refresh-on-focus';
import {
  CONVERSATIONS_INITIAL,
  conversationListReducer,
} from '@/state/conversation-list';
import { useSession } from '@/state/session';
import { Alert } from '@/ui/alert';
import {
  Avatar,
  Button,
  Card,
  CountBadge,
  ErrorState,
  listContent,
  Loading,
  Notice,
  SectionTitle,
} from '@/ui/kit';
import { colors, radius, shadow, space, type } from '@/ui/theme';

interface Tile {
  emoji: string;
  title: string;
  subtitle: string;
  href: Href<string>;
  countKey?: 'candidates' | 'reflections';
}

const TILES: Tile[] = [
  { emoji: '🧠', title: 'Memories', subtitle: 'What it remembers', href: '/(main)/memories' },
  { emoji: '🎯', title: 'Goals', subtitle: "What you're working on", href: '/(main)/goals' },
  {
    emoji: '✅',
    title: 'Review',
    subtitle: 'Memories to approve',
    href: '/(main)/candidates',
    countKey: 'candidates',
  },
  {
    emoji: '💡',
    title: 'Reflections',
    subtitle: 'What it noticed',
    href: '/(main)/reflections',
    countKey: 'reflections',
  },
  { emoji: '🌱', title: 'Evolution', subtitle: 'How it has grown', href: '/(main)/evolution' },
  { emoji: '🪞', title: 'Self-portrait', subtitle: 'What it knows about you', href: '/(main)/portrait' },
];

interface Pending {
  candidates: number;
  reflections: number;
}

export default function HomeScreen() {
  const router = useRouter();
  const { width } = useWindowDimensions();
  // Six shortcuts: an even 3 x 2 on wide screens, 2 x 3 on phones.
  const tileBasis = width >= 560 ? '31%' : '46%';
  const twin = useSession((s) => s.twin);
  const setTwin = useSession((s) => s.setTwin);
  const [state, dispatch] = useReducer(conversationListReducer, CONVERSATIONS_INITIAL);
  // Bumped by the retry button; re-runs the effect without duplicating it.
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [creating, setCreating] = useState(false);
  const [createFailure, setCreateFailure] = useState<ApiFailure | null>(null);
  const [pending, setPending] = useState<Pending>({ candidates: 0, reflections: 0 });

  const loadPending = useCallback(() => {
    // Counts are a nudge, not essential: failures leave the last known value.
    return Promise.allSettled([
      api.listCandidates('pending').then((r) =>
        setPending((p) => ({ ...p, candidates: r.items.length })),
      ),
      api.listReflections('pending').then((r) =>
        setPending((p) => ({ ...p, reflections: r.items.length })),
      ),
    ]);
  }, []);

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
          dispatch({ type: 'failed', failure: logApiFailure('GET /v1/conversations', err) });
        }
      });
    void loadPending();
    return () => {
      cancelled = true;
    };
  }, [loadAttempt, loadPending]);

  // Coming back from a chat or the profile: pick up new conversations, new
  // titles, profile changes and new things to review. Quietly: a failed
  // background refresh keeps what is on screen rather than showing an error.
  useRefreshOnFocus(() =>
    Promise.allSettled([
      api.listConversations().then((res) => dispatch({ type: 'loaded', items: res.items })),
      api.getTwin().then(setTwin),
      loadPending(),
    ]),
  );

  const retry = useCallback(() => setLoadAttempt((n) => n + 1), []);

  const [signingOut, setSigningOut] = useState(false);
  const signOut = useCallback(() => {
    if (signingOut) return;
    setSigningOut(true);
    // The auth listener in the root layout clears the session and the gate
    // sends the person to the sign-in screen.
    supabase.auth
      .signOut()
      .catch(() => {
        Alert.alert('Could not sign out', 'Please try again.');
      })
      .finally(() => setSigningOut(false));
  }, [signingOut]);

  // Not an async onPress handler: a rejected createConversation() there is
  // unhandled for exactly the same reason.
  const newConversation = useCallback(() => {
    if (creating) return;
    setCreating(true);
    setCreateFailure(null);
    api
      .createConversation()
      .then((created) => {
        router.push({ pathname: '/(main)/chat/[id]', params: { id: created.id } });
      })
      .catch((err: unknown) => {
        setCreateFailure(logApiFailure('POST /v1/conversations', err));
      })
      .finally(() => setCreating(false));
  }, [creating, router]);

  const name = twin?.display_name ?? 'Your Twin';
  const style = styleInfo(twin?.profile.communication_style_preset ?? 'neutral');
  const toReview = pending.candidates + pending.reflections;

  const header = (
    <View style={styles.headerWrap}>
      <View style={styles.topBar}>
        <Text style={styles.brand}>🪞 MirrorSelf</Text>
        <View style={styles.topActions}>
          <Pressable
            onPress={() => router.push('/(main)/profile')}
            accessibilityRole="button"
            hitSlop={6}
            style={({ pressed }) => [styles.topAction, pressed && styles.topActionPressed]}
          >
            <Text style={styles.topActionText}>Profile</Text>
          </Pressable>
          <Pressable
            onPress={signOut}
            disabled={signingOut}
            accessibilityRole="button"
            hitSlop={6}
            style={({ pressed }) => [styles.topAction, pressed && styles.topActionPressed]}
          >
            <Text style={[styles.topActionText, styles.topActionMuted]}>
              {signingOut ? 'Signing out…' : 'Sign out'}
            </Text>
          </Pressable>
        </View>
      </View>

      <View style={styles.hero}>
        <View style={styles.heroTop}>
          <Avatar name={name} size={56} />
          <View style={styles.heroText}>
            <Text style={styles.greeting}>{greeting()}</Text>
            <Text style={styles.heroName} numberOfLines={1}>
              {name}
            </Text>
            <Text style={styles.heroStyle}>
              {style.emoji} {style.label} · {style.description.toLowerCase()}
            </Text>
          </View>
        </View>
        <Button
          title={creating ? 'Starting…' : `💬  Talk to ${name}`}
          size="lg"
          onPress={newConversation}
          loading={creating}
          style={styles.heroButton}
        />
        {createFailure ? (
          <Text style={styles.createError}>
            {apiFailureMessage(createFailure, config.apiUrl)}
          </Text>
        ) : null}
      </View>

      {toReview > 0 ? (
        <Card
          onPress={() =>
            router.push(pending.candidates > 0 ? '/(main)/candidates' : '/(main)/reflections')
          }
          style={styles.nudge}
          accessibilityLabel="Things waiting for your review"
        >
          <View style={styles.nudgeRow}>
            <Text style={styles.nudgeEmoji}>✨</Text>
            <View style={styles.flex}>
              <Text style={type.bodyStrong}>
                {name} has {plural(toReview, 'thing')} for you to look at
              </Text>
              <Text style={type.small}>
                {[
                  pending.candidates ? plural(pending.candidates, 'memory', 'memories') : null,
                  pending.reflections ? plural(pending.reflections, 'reflection') : null,
                ]
                  .filter(Boolean)
                  .join(' · ')}
              </Text>
            </View>
            <Text style={styles.chevron}>›</Text>
          </View>
        </Card>
      ) : null}

      <SectionTitle>Your Twin</SectionTitle>
      <View style={styles.tiles}>
        {TILES.map((t) => {
          const count = t.countKey ? pending[t.countKey] : 0;
          return (
            <Pressable
              key={t.title}
              onPress={() => router.push(t.href)}
              accessibilityRole="button"
              accessibilityLabel={count ? `${t.title}, ${count} waiting` : t.title}
              style={({ pressed }) => [
                styles.tile,
                { flexBasis: tileBasis },
                pressed && styles.tilePressed,
              ]}
            >
              <View style={styles.tileTop}>
                <Text style={styles.tileEmoji}>{t.emoji}</Text>
                <CountBadge count={count} />
              </View>
              <Text style={styles.tileTitle}>{t.title}</Text>
              <Text style={styles.tileSub}>{t.subtitle}</Text>
            </Pressable>
          );
        })}
      </View>

      <SectionTitle>Conversations</SectionTitle>
    </View>
  );

  if (state.status === 'failed') {
    return (
      <FlatList
        style={styles.list}
        contentContainerStyle={listContent}
        data={[]}
        renderItem={null}
        ListHeaderComponent={header}
        ListEmptyComponent={
          <ErrorState
            title="Could not load your conversations"
            message={apiFailureMessage(state.failure, config.apiUrl)}
            onRetry={retry}
          />
        }
      />
    );
  }

  return (
    <FlatList
      style={styles.list}
      contentContainerStyle={listContent}
      data={state.status === 'ready' ? state.items : []}
      keyExtractor={(c) => c.id}
      ListHeaderComponent={header}
      renderItem={({ item }) => (
        <Card
          onPress={() => router.push({ pathname: '/(main)/chat/[id]', params: { id: item.id } })}
          style={styles.convo}
        >
          <View style={styles.convoRow}>
            <View style={styles.flex}>
              <Text style={styles.convoTitle} numberOfLines={1}>
                {item.title ?? 'New conversation'}
              </Text>
              <Text style={type.caption}>{relativeTime(item.updated_at)}</Text>
            </View>
            <Text style={styles.chevron}>›</Text>
          </View>
        </Card>
      )}
      ListEmptyComponent={
        state.status === 'loading' ? (
          <Loading label="Loading conversations" />
        ) : (
          <Notice
            tone="primary"
            title="No conversations yet"
            body={`Say hello to ${name}. Tell it about your day, your plans or what's on your mind — it gets to know you as you talk.`}
          />
        )
      }
    />
  );
}

const styles = StyleSheet.create({
  list: { flex: 1, backgroundColor: colors.bg },
  flex: { flex: 1 },
  headerWrap: { gap: space.md },
  topBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingTop: space.xs,
  },
  brand: { fontSize: 17, fontWeight: '800', color: colors.ink, letterSpacing: -0.2 },
  topActions: { flexDirection: 'row', gap: space.xs },
  topAction: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: radius.sm },
  topActionPressed: { backgroundColor: colors.primarySoft },
  topActionText: { color: colors.primary, fontWeight: '700', fontSize: 14 },
  topActionMuted: { color: colors.muted },

  hero: {
    backgroundColor: colors.surface,
    borderRadius: radius.xl,
    borderWidth: 1,
    borderColor: colors.border,
    padding: space.xl,
    gap: space.lg,
    ...shadow.card,
  },
  heroTop: { flexDirection: 'row', alignItems: 'center', gap: space.lg },
  heroText: { flex: 1, gap: 2 },
  greeting: { ...type.small },
  heroName: { ...type.display },
  heroStyle: { ...type.small, color: colors.text },
  heroButton: { alignSelf: 'stretch' },
  createError: { fontSize: 13, color: colors.danger },

  nudge: { backgroundColor: colors.primarySoft, borderColor: colors.primaryBorder },
  nudgeRow: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  nudgeEmoji: { fontSize: 22 },

  tiles: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm },
  tile: {
    flexGrow: 1,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 14,
    gap: 2,
    ...shadow.card,
  },
  tilePressed: { backgroundColor: colors.surfaceAlt, borderColor: colors.borderStrong },
  tileTop: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: 6,
  },
  tileEmoji: { fontSize: 24 },
  tileTitle: { fontSize: 15, fontWeight: '700', color: colors.ink },
  tileSub: { ...type.caption },

  convo: { paddingVertical: 14 },
  convoRow: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  convoTitle: { ...type.bodyStrong },
  chevron: { fontSize: 24, color: colors.faint, marginTop: -2 },
});
