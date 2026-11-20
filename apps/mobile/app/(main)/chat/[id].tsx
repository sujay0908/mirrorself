/**
 * Chat screen — send a message, see the twin reply, reopen history.
 *
 * Reliability rules this screen keeps:
 *
 * - The draft stays in the box until the server has stored the exchange. A
 *   failed send never loses what the person typed.
 * - Every send carries an idempotency key that is reused when the same draft
 *   is retried, so a retry after a timeout or a dropped connection returns
 *   the stored reply instead of producing a second turn.
 * - One send at a time; double taps and Enter-mashing are ignored.
 * - Loading and sending failures are shown with a reason and a way to retry.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { useLocalSearchParams } from 'expo-router';

import { api, APIError } from '@/api/client';
import type { Message } from '@/api/types';
import { MessageBubble } from '@/components/MessageBubble';
import { keyForSend, type PendingSend } from '@/lib/idempotency';
import { isRetryable, retryAfterSeconds, userErrorMessage } from '@/lib/user-errors';
import { useSession } from '@/state/session';
import { Avatar, Centered, ErrorState, WEB_NO_OUTLINE } from '@/ui/kit';
import { colors, CONTENT_MAX_WIDTH, radius, space, type } from '@/ui/theme';

const MAX_MESSAGE_CHARS = 8000;
// "Still processing" answers are retried automatically for about this long.
const IN_PROGRESS_RETRIES = 10;

const STARTERS = [
  'Here’s a little about me…',
  'Help me plan my week',
  'What do you know about me so far?',
];

type LoadState = { status: 'loading' } | { status: 'ready' } | { status: 'failed'; reason: string };

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export default function ChatScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const twinName = useSession((s) => s.twin?.display_name ?? 'your Twin');
  const [messages, setMessages] = useState<Message[]>([]);
  const [load, setLoad] = useState<LoadState>({ status: 'loading' });
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<{ text: string; retryable: boolean } | null>(null);
  const sendingRef = useRef(false);
  const pendingRef = useRef<PendingSend | null>(null);
  const listRef = useRef<FlatList<Message>>(null);
  const inputRef = useRef<TextInput>(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    setLoad({ status: 'loading' });
    api
      .listMessages(id)
      .then((res) => {
        if (cancelled) return;
        setMessages(res.items);
        setLoad({ status: 'ready' });
      })
      .catch((err: unknown) => {
        if (!cancelled) setLoad({ status: 'failed', reason: userErrorMessage(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [id, loadAttempt]);

  const scrollToEnd = useCallback(() => {
    requestAnimationFrame(() => listRef.current?.scrollToEnd({ animated: true }));
  }, []);

  const send = useCallback(async () => {
    const content = input.trim();
    if (!id || !content || sendingRef.current) return;
    sendingRef.current = true;
    setSending(true);
    setSendError(null);

    const pending = keyForSend(pendingRef.current, content);
    pendingRef.current = pending;
    try {
      let attempt = 0;
      for (;;) {
        try {
          const pair = await api.postMessage(id, content, pending.key);
          setMessages((prev) => {
            // A replayed exchange may already be on screen.
            const seen = new Set(prev.map((m) => m.id));
            const fresh = [pair.user_message, pair.twin_message].filter((m) => !seen.has(m.id));
            return [...prev, ...fresh];
          });
          pendingRef.current = null;
          // Only clear the box if it still holds what was sent.
          setInput((current) => (current.trim() === content ? '' : current));
          scrollToEnd();
          return;
        } catch (err) {
          const inProgress = err instanceof APIError && err.code === 'message_in_progress';
          if (inProgress && attempt < IN_PROGRESS_RETRIES) {
            attempt += 1;
            await sleep((retryAfterSeconds(err) ?? 3) * 1000);
            continue;
          }
          throw err;
        }
      }
    } catch (err) {
      setSendError({ text: userErrorMessage(err), retryable: isRetryable(err) });
    } finally {
      sendingRef.current = false;
      setSending(false);
    }
  }, [id, input, scrollToEnd]);

  const onKeyPress = useCallback(
    (e: { nativeEvent: { key: string; shiftKey?: boolean } }) => {
      // Web: Enter sends, Shift+Enter adds a line.
      if (Platform.OS === 'web' && e.nativeEvent.key === 'Enter' && !e.nativeEvent.shiftKey) {
        (e as unknown as { preventDefault?: () => void }).preventDefault?.();
        void send();
      }
    },
    [send],
  );

  const pickStarter = useCallback((text: string) => {
    setInput(text.endsWith('…') ? text.slice(0, -1) + ' ' : text);
    inputRef.current?.focus();
  }, []);

  const trimmed = input.trim();
  const tooLong = trimmed.length > MAX_MESSAGE_CHARS;
  const ready = load.status === 'ready';
  const canSend = trimmed.length > 0 && !tooLong && !sending && ready;

  if (load.status === 'failed') {
    return (
      <Centered>
        <ErrorState
          title="Could not load this conversation"
          message={load.reason}
          onRetry={() => setLoadAttempt((n) => n + 1)}
        />
      </Centered>
    );
  }

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      {load.status === 'loading' ? (
        <View style={styles.loading}>
          <ActivityIndicator color={colors.primary} accessibilityLabel="Loading conversation" />
        </View>
      ) : (
        <FlatList
          ref={listRef}
          style={styles.list}
          data={messages}
          keyExtractor={(m) => m.id}
          renderItem={({ item }) => <MessageBubble message={item} />}
          contentContainerStyle={styles.listContent}
          onContentSizeChange={scrollToEnd}
          keyboardShouldPersistTaps="handled"
          ListEmptyComponent={
            sending ? null : (
              <View style={styles.welcome}>
                <Avatar name={twinName} size={64} />
                <Text style={styles.welcomeTitle}>Say hi to {twinName}</Text>
                <Text style={styles.welcomeBody}>
                  It learns from what you share, and it asks before it remembers
                  anything.
                </Text>
                <View style={styles.starters}>
                  {STARTERS.map((s) => (
                    <Pressable
                      key={s}
                      onPress={() => pickStarter(s)}
                      accessibilityRole="button"
                      style={({ pressed }) => [styles.starter, pressed && styles.starterPressed]}
                    >
                      <Text style={styles.starterText}>{s}</Text>
                    </Pressable>
                  ))}
                </View>
              </View>
            )
          }
          ListFooterComponent={
            sending ? (
              <View style={styles.pending}>
                <View style={styles.pendingUserRow}>
                  <View style={styles.pendingUser}>
                    <Text style={styles.pendingUserText}>{trimmed}</Text>
                  </View>
                </View>
                <View style={styles.thinking}>
                  <Avatar name={twinName} size={30} />
                  <View style={styles.thinkingBubble}>
                    <ActivityIndicator size="small" color={colors.muted} />
                    <Text style={styles.thinkingText}>{twinName} is thinking…</Text>
                  </View>
                </View>
              </View>
            ) : null
          }
        />
      )}

      <View style={styles.bottom}>
        <View style={styles.bottomColumn}>
          {sendError ? (
            <View style={styles.sendError} accessibilityLiveRegion="polite">
              <Text style={styles.sendErrorText}>{sendError.text}</Text>
              <View style={styles.sendErrorActions}>
                {sendError.retryable ? (
                  <Pressable onPress={() => void send()} accessibilityRole="button" hitSlop={6}>
                    <Text style={styles.sendErrorAction}>Retry</Text>
                  </Pressable>
                ) : null}
                <Pressable onPress={() => setSendError(null)} accessibilityRole="button" hitSlop={6}>
                  <Text style={styles.sendErrorDismiss}>Dismiss</Text>
                </Pressable>
              </View>
            </View>
          ) : null}

          <View style={styles.composer}>
            <TextInput
              ref={inputRef}
              value={input}
              onChangeText={setInput}
              onKeyPress={onKeyPress}
              placeholder={`Message ${twinName}…`}
              placeholderTextColor={colors.faint}
              accessibilityLabel="Message"
              style={[styles.input, WEB_NO_OUTLINE]}
              editable={!sending && ready}
              multiline
              // Web renders a two-row textarea by default; start at one line.
              numberOfLines={1}
              maxLength={MAX_MESSAGE_CHARS + 1}
            />
            <Pressable
              onPress={() => void send()}
              disabled={!canSend}
              accessibilityRole="button"
              accessibilityLabel="Send message"
              style={({ pressed }) => [
                styles.send,
                !canSend && styles.sendDisabled,
                pressed && canSend && styles.sendPressed,
              ]}
            >
              {sending ? (
                <ActivityIndicator size="small" color={colors.onPrimary} />
              ) : (
                <Text style={styles.sendText}>↑</Text>
              )}
            </Pressable>
          </View>
          {tooLong ? (
            <Text style={styles.limit}>
              Messages can be up to {MAX_MESSAGE_CHARS.toLocaleString()} characters.
            </Text>
          ) : Platform.OS === 'web' ? (
            <Text style={styles.hint}>Enter to send · Shift + Enter for a new line</Text>
          ) : null}
        </View>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  loading: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  list: { flex: 1 },
  listContent: {
    width: '100%',
    maxWidth: CONTENT_MAX_WIDTH,
    alignSelf: 'center',
    paddingHorizontal: space.lg,
    paddingTop: space.lg,
    paddingBottom: space.sm,
    flexGrow: 1,
  },

  welcome: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: space.xxxl,
    gap: space.sm,
  },
  welcomeTitle: { ...type.title, marginTop: space.sm },
  welcomeBody: { ...type.body, color: colors.muted, textAlign: 'center', maxWidth: 340 },
  starters: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'center',
    gap: space.sm,
    marginTop: space.lg,
  },
  starter: {
    paddingHorizontal: 14,
    paddingVertical: 9,
    borderRadius: radius.pill,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  starterPressed: { backgroundColor: colors.primarySoft, borderColor: colors.primaryBorder },
  starterText: { fontSize: 14, color: colors.text, fontWeight: '500' },

  pending: { gap: space.sm, marginTop: space.xs },
  pendingUserRow: { alignItems: 'flex-end' },
  pendingUser: {
    maxWidth: '85%',
    backgroundColor: colors.primary,
    opacity: 0.75,
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: radius.lg,
    borderTopRightRadius: 6,
  },
  pendingUserText: { fontSize: 15, lineHeight: 22, color: colors.onPrimary },
  thinking: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  thinkingBubble: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.sm,
    paddingHorizontal: 14,
    paddingVertical: 10,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.lg,
    borderTopLeftRadius: 6,
  },
  thinkingText: { ...type.small },

  bottom: {
    borderTopWidth: 1,
    borderTopColor: colors.border,
    backgroundColor: colors.surface,
  },
  bottomColumn: {
    width: '100%',
    maxWidth: CONTENT_MAX_WIDTH,
    alignSelf: 'center',
    paddingHorizontal: space.md,
    paddingTop: space.sm,
    paddingBottom: space.sm,
    gap: 6,
  },
  sendError: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: space.md,
    backgroundColor: colors.dangerSoft,
    borderRadius: radius.md,
    paddingHorizontal: space.md,
    paddingVertical: space.sm,
  },
  sendErrorText: { flex: 1, minWidth: 180, color: colors.danger, fontSize: 13 },
  sendErrorActions: { flexDirection: 'row', gap: space.lg },
  sendErrorAction: { color: colors.primary, fontWeight: '700' },
  sendErrorDismiss: { color: colors.muted, fontWeight: '600' },
  composer: { flexDirection: 'row', alignItems: 'flex-end', gap: space.sm },
  input: {
    flex: 1,
    minHeight: 44,
    maxHeight: 140,
    backgroundColor: colors.surfaceAlt,
    borderWidth: 1.5,
    borderColor: colors.border,
    borderRadius: radius.xl,
    paddingHorizontal: space.lg,
    paddingTop: 11,
    paddingBottom: 11,
    fontSize: 15,
    lineHeight: 20,
    color: colors.ink,
  },
  send: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
  },
  sendPressed: { backgroundColor: colors.primaryPressed },
  sendDisabled: { backgroundColor: colors.borderStrong },
  sendText: { color: colors.onPrimary, fontSize: 20, fontWeight: '800', marginTop: -2 },
  hint: { ...type.caption, color: colors.faint, textAlign: 'center' },
  limit: { color: colors.danger, fontSize: 12, textAlign: 'center' },
});
