/**
 * Full-screen spinner that explains a long wait.
 *
 * The hosted API sleeps after a quiet spell and takes up to a minute to wake.
 * A bare spinner for that long looks like a broken app, so after a few
 * seconds this says what is happening.
 */

import { useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';

import { colors, space, type } from '@/ui/theme';

const HINT_AFTER_MS = 4000;

export function LoadingScreen() {
  const [slow, setSlow] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setSlow(true), HINT_AFTER_MS);
    return () => clearTimeout(timer);
  }, []);

  return (
    <View style={styles.container} accessibilityLabel="Loading">
      <View style={styles.mark}>
        <Text style={styles.markEmoji}>🪞</Text>
      </View>
      <ActivityIndicator color={colors.primary} />
      {slow ? (
        <Text style={styles.hint}>
          Waking up the server. After a quiet spell this can take up to a minute.
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: space.xxl,
    gap: space.lg,
    backgroundColor: colors.bg,
  },
  mark: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: colors.primarySoft,
    alignItems: 'center',
    justifyContent: 'center',
  },
  markEmoji: { fontSize: 30 },
  hint: { ...type.small, textAlign: 'center', maxWidth: 300 },
});
