import { StyleSheet, Text, View } from 'react-native';

import type { Message } from '@/api/types';

interface Props {
  message: Message;
}

export function MessageBubble({ message }: Props) {
  const isUser = message.role === 'user';
  return (
    <View
      style={[
        styles.bubble,
        isUser ? styles.user : styles.twin,
      ]}
    >
      <Text style={isUser ? styles.userText : styles.twinText}>
        {message.content}
      </Text>
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
  userText: {
    color: '#ffffff',
  },
  twinText: {
    color: '#111827',
  },
});
