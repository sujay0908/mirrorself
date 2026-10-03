/**
 * Message bubble, with Sprint 4 tap-to-reveal citations.
 *
 * A twin bubble that was answered with the help of retrieved memories
 * shows a small "N memories used" affordance. Tapping it toggles a
 * citations panel below the bubble that links each memory id to its
 * detail screen (where provenance lives). Active goals that reached the
 * context are shown the same way under "N goals considered".
 */

import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useRouter } from 'expo-router';

import type { Message } from '@/api/types';
import { citationsFromMessage } from '@/lib/citations';

interface Props {
  message: Message;
}

export function MessageBubble({ message }: Props) {
  const router = useRouter();
  const [expanded, setExpanded] = useState(false);
  const isUser = message.role === 'user';
  const { memoryIds, goalIds, hasAny: hasCitations } =
    citationsFromMessage(message);

  return (
    <View>
      <View style={[styles.bubble, isUser ? styles.user : styles.twin]}>
        <Text style={isUser ? styles.userText : styles.twinText}>
          {message.content}
        </Text>
      </View>
      {hasCitations ? (
        <Pressable
          onPress={() => setExpanded((v) => !v)}
          style={styles.cites}
        >
          <Text style={styles.citesText}>
            {memoryIds.length > 0
              ? `${memoryIds.length} ${memoryIds.length === 1 ? 'memory' : 'memories'} used`
              : null}
            {memoryIds.length > 0 && goalIds.length > 0 ? ' · ' : ''}
            {goalIds.length > 0
              ? `${goalIds.length} ${goalIds.length === 1 ? 'goal' : 'goals'} considered`
              : null}
            {expanded ? ' ▴' : ' ▾'}
          </Text>
        </Pressable>
      ) : null}
      {hasCitations && expanded ? (
        <View style={styles.panel}>
          {memoryIds.map((mid) => (
            <Pressable
              key={mid}
              onPress={() =>
                router.push({
                  pathname: '/(main)/memories/[id]',
                  params: { id: mid },
                })
              }
              style={styles.panelRow}
            >
              <Text style={styles.panelRowKind}>Memory</Text>
              <Text style={styles.panelRowId}>{mid.slice(0, 8)}…</Text>
            </Pressable>
          ))}
          {goalIds.map((gid) => (
            <Pressable
              key={gid}
              onPress={() =>
                router.push({
                  pathname: '/(main)/goals/[id]',
                  params: { id: gid },
                })
              }
              style={styles.panelRow}
            >
              <Text style={styles.panelRowKind}>Goal</Text>
              <Text style={styles.panelRowId}>{gid.slice(0, 8)}…</Text>
            </Pressable>
          ))}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  bubble: {
    padding: 12,
    borderRadius: 16,
    marginVertical: 4,
    maxWidth: '85%',
  },
  user: {
    alignSelf: 'flex-end',
    backgroundColor: '#4f46e5',
  },
  twin: {
    alignSelf: 'flex-start',
    backgroundColor: '#e5e7eb',
  },
  userText: { color: '#ffffff' },
  twinText: { color: '#111827' },
  cites: {
    alignSelf: 'flex-start',
    marginTop: 2,
    marginBottom: 2,
    paddingHorizontal: 8,
    paddingVertical: 4,
  },
  citesText: {
    fontSize: 11,
    color: '#6b7280',
    fontWeight: '600',
  },
  panel: {
    alignSelf: 'flex-start',
    backgroundColor: '#f3f4f6',
    borderRadius: 10,
    padding: 8,
    marginBottom: 6,
    gap: 4,
    maxWidth: '85%',
  },
  panelRow: {
    flexDirection: 'row',
    gap: 8,
    paddingVertical: 4,
    alignItems: 'center',
  },
  panelRowKind: {
    fontSize: 10,
    fontWeight: '700',
    color: '#4338ca',
    backgroundColor: '#eef2ff',
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 6,
    textTransform: 'uppercase',
  },
  panelRowId: { fontSize: 12, color: '#4338ca', fontWeight: '600' },
});
