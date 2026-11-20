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

const MAX_MESSAGE_CHARS = 8000;
// "Still processing" answers are retried automatically for about this long.
const IN_PROGRESS_RETRIES = 10;

type LoadState = { status: 'loading' } | { status: 'ready' } | { status: 'failed'; reason: string };

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export default function ChatScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [messages, setMessages] = useState<Message[]>([]);
  const [load, setLoad] = useState<LoadState>({ status: 'loading' });
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<{ text: string; retryable: boolean } | null>(null);
  const sendingRef = useRef(false);
  const pendingRef = useRef<PendingSend | null>(null);
  const listRef = useRef<FlatList<Message>>(null);

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

  const trimmed = input.trim();
  const tooLong = trimmed.length > MAX_MESSAGE_CHARS;
  const canSend = trimmed.length > 0 && !tooLong && !sending;

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      {load.status === 'loading' ? (
        <ActivityIndicator style={styles.loading} accessibilityLabel="Loading conversation" />
      ) : load.status === 'failed' ? (
        <View style={styles.centered}>
          <Text style={styles.errorTitle}>Could not load this conversation</Text>
          <Text style={styles.errorBody}>{load.reason}</Text>
          <Pressable
            style={styles.retry}
            onPress={() => setLoadAttempt((n) => n + 1)}
            accessibilityRole="button"
          >
            <Text style={styles.retryText}>Try again</Text>
          </Pressable>
        </View>
      ) : (
        <FlatList
          ref={listRef}
          data={messages}
          keyExtractor={(m) => m.id}
          renderItem={({ item }) => <MessageBubble message={item} />}
          contentContainerStyle={styles.list}
          onContentSizeChange={scrollToEnd}
          ListEmptyComponent={
            sending ? null : (
              <Text style={styles.empty}>
                Say hello. Your Twin learns from what you tell it, and you
                approve anything it wants to remember.
              </Text>
            )
          }
          ListFooterComponent={
            sending ? (
              <View style={styles.pending}>
                <Text style={styles.pendingUser}>{trimmed}</Text>
                <View style={styles.thinking}>
                  <ActivityIndicator size="small" />
                  <Text style={styles.thinkingText}>Your Twin is replying…</Text>
                </View>
              </View>
            ) : null
          }
        />
      )}

      {sendError ? (
        <View style={styles.sendError} accessibilityLiveRegion="polite">
          <Text style={styles.sendErrorText}>{sendError.text}</Text>
          {sendError.retryable ? (
            <Pressable onPress={() => void send()} accessibilityRole="button">
              <Text style={styles.sendErrorAction}>Retry</Text>
            </Pressable>
          ) : null}
          <Pressable onPress={() => setSendError(null)} accessibilityRole="button">
            <Text style={styles.sendErrorDismiss}>Dismiss</Text>
          </Pressable>
        </View>
      ) : null}

      <View style={styles.composer}>
        <TextInput
          value={input}
          onChangeText={setInput}
          onKeyPress={onKeyPress}
          placeholder="Message your twin…"
          accessibilityLabel="Message"
          style={styles.input}
          editable={!sending && load.status === 'ready'}
          multiline
          maxLength={MAX_MESSAGE_CHARS + 1}
        />
        <Pressable
          onPress={() => void send()}
          disabled={!canSend || load.status !== 'ready'}
          accessibilityRole="button"
          accessibilityLabel="Send message"
          style={[styles.send, (!canSend || load.status !== 'ready') && styles.sendDisabled]}
        >
          <Text style={styles.sendText}>{sending ? '…' : 'Send'}</Text>
        </Pressable>
      </View>
      {tooLong ? (
        <Text style={styles.limit}>
          Messages can be up to {MAX_MESSAGE_CHARS.toLocaleString()} characters.
        </Text>
      ) : null}
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#ffffff' },
  loading: { marginTop: 40 },
  list: { padding: 16, flexGrow: 1 },
  empty: { textAlign: 'center', color: '#6b7280', marginTop: 40, paddingHorizontal: 24 },
  centered: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24, gap: 8 },
  errorTitle: { fontSize: 16, fontWeight: '700', textAlign: 'center' },
  errorBody: { fontSize: 14, color: '#4b5563', textAlign: 'center' },
  retry: {
    marginTop: 8,
    backgroundColor: '#4f46e5',
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderRadius: 8,
  },
  retryText: { color: '#ffffff', fontWeight: '600' },
  pending: { marginTop: 8, gap: 8 },
  pendingUser: {
    alignSelf: 'flex-end',
    maxWidth: '80%',
    backgroundColor: '#c7d2fe',
    color: '#1e1b4b',
    padding: 10,
    borderRadius: 12,
  },
  thinking: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  thinkingText: { color: '#6b7280', fontSize: 13 },
  sendError: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: 12,
    backgroundColor: '#fef2f2',
    borderTopWidth: 1,
    borderTopColor: '#fecaca',
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  sendErrorText: { flex: 1, minWidth: 180, color: '#991b1b', fontSize: 13 },
  sendErrorAction: { color: '#4f46e5', fontWeight: '700' },
  sendErrorDismiss: { color: '#6b7280' },
  composer: {
    flexDirection: 'row',
    padding: 12,
    gap: 8,
    borderTopWidth: 1,
    borderTopColor: '#e5e7eb',
    alignItems: 'flex-end',
  },
  input: {
    flex: 1,
    borderWidth: 1,
    borderColor: '#d1d5db',
    borderRadius: 12,
    padding: 10,
    maxHeight: 120,
  },
  send: {
    backgroundColor: '#4f46e5',
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderRadius: 12,
  },
  sendDisabled: { backgroundColor: '#9ca3af' },
  sendText: { color: '#ffffff', fontWeight: '600' },
  limit: { color: '#b91c1c', fontSize: 12, paddingHorizontal: 12, paddingBottom: 8 },
});
