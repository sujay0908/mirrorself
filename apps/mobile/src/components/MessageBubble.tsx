/**
 * One chat message.
 *
 * Twin replies sit on the left beside the Twin's avatar; yours sit on the
 * right in the brand colour. Under a reply, two optional, tappable notes:
 * what the Twin drew on (memories and goals, shown by what they say) and what
 * it learned since your last message.
 */

import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { Message } from '@/api/types';
import { GoalPreview, MemoryPreview } from '@/components/RefPreview';
import { citationsFromMessage } from '@/lib/citations';
import { friendlyEvent, plural } from '@/lib/format';
import { learningFromMessage, learningHeadline } from '@/lib/learning';
import { useSession } from '@/state/session';
import { Avatar } from '@/ui/kit';
import { colors, radius, space, type } from '@/ui/theme';

interface Props {
  message: Message;
}

export function MessageBubble({ message }: Props) {
  const twinName = useSession((s) => s.twin?.display_name ?? 'Twin');
  const [showSources, setShowSources] = useState(false);
  const [showLearning, setShowLearning] = useState(false);

  if (message.role === 'user') {
    return (
      <View style={styles.userRow}>
        <View style={[styles.bubble, styles.userBubble]}>
          <Text style={styles.userText} selectable>
            {message.content}
          </Text>
        </View>
      </View>
    );
  }

  const { memoryIds, goalIds, hasAny: hasSources } = citationsFromMessage(message);
  const learning = learningFromMessage(message);
  const sourceLabel = [
    memoryIds.length ? plural(memoryIds.length, 'memory', 'memories') : null,
    goalIds.length ? plural(goalIds.length, 'goal') : null,
  ]
    .filter(Boolean)
    .join(' and ');

  return (
    <View style={styles.twinRow}>
      <Avatar name={twinName} size={30} />
      <View style={styles.twinColumn}>
        <View style={[styles.bubble, styles.twinBubble]}>
          <Text style={styles.twinText} selectable>
            {message.content}
          </Text>
        </View>

        {hasSources ? (
          <Pressable
            onPress={() => setShowSources((v) => !v)}
            accessibilityRole="button"
            accessibilityState={{ expanded: showSources }}
            style={({ pressed }) => [styles.note, pressed && styles.notePressed]}
          >
            <Text style={styles.noteText}>
              🔎 Used {sourceLabel} {showSources ? '▴' : '▾'}
            </Text>
          </Pressable>
        ) : null}
        {hasSources && showSources ? (
          <View style={styles.panel}>
            {memoryIds.map((id) => (
              <MemoryPreview key={id} id={id} />
            ))}
            {goalIds.map((id) => (
              <GoalPreview key={id} id={id} />
            ))}
          </View>
        ) : null}

        {learning.hasAny ? (
          <Pressable
            onPress={() => setShowLearning((v) => !v)}
            accessibilityRole="button"
            accessibilityState={{ expanded: showLearning }}
            style={({ pressed }) => [styles.note, styles.learnNote, pressed && styles.notePressed]}
          >
            <Text style={[styles.noteText, styles.learnText]}>
              ✨ {learningHeadline(learning)} {showLearning ? '▴' : '▾'}
            </Text>
          </Pressable>
        ) : null}
        {learning.hasAny && showLearning ? (
          <View style={styles.panel}>
            {learning.items.map((it) => {
              const e = friendlyEvent(it.event_type, it.summary);
              return (
                <View key={it.id} style={styles.learnRow}>
                  <Text style={styles.learnEmoji}>{e.emoji}</Text>
                  <View style={styles.flex}>
                    <Text style={type.caption}>{e.leadText}</Text>
                    <Text style={styles.learnTitle}>{e.title}</Text>
                  </View>
                </View>
              );
            })}
          </View>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  userRow: { alignItems: 'flex-end', marginVertical: space.xs },
  twinRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: space.sm,
    marginVertical: space.xs,
    paddingRight: '10%',
  },
  twinColumn: { flexShrink: 1, gap: 6, alignItems: 'flex-start' },
  bubble: { paddingHorizontal: 14, paddingVertical: 10, borderRadius: radius.lg },
  userBubble: {
    maxWidth: '85%',
    backgroundColor: colors.primary,
    borderTopRightRadius: 6,
  },
  twinBubble: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderTopLeftRadius: 6,
  },
  userText: { fontSize: 15, lineHeight: 22, color: colors.onPrimary },
  twinText: { fontSize: 15, lineHeight: 22, color: colors.ink },
  note: {
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: radius.pill,
    backgroundColor: colors.surfaceAlt,
    borderWidth: 1,
    borderColor: colors.border,
  },
  notePressed: { backgroundColor: colors.primarySoft },
  noteText: { fontSize: 12, fontWeight: '600', color: colors.muted },
  learnNote: { backgroundColor: colors.tealSoft, borderColor: colors.tealBorder },
  learnText: { color: colors.teal },
  panel: { alignSelf: 'stretch', gap: 6, maxWidth: 480 },
  learnRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.sm,
    paddingVertical: space.sm,
    paddingHorizontal: space.md,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  learnEmoji: { fontSize: 18 },
  learnTitle: { fontSize: 14, fontWeight: '600', color: colors.ink },
});
