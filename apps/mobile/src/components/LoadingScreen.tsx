/**
 * Full-screen spinner that explains a long wait.
 *
 * The hosted API sleeps after a quiet spell and takes up to a minute to wake.
 * A bare spinner for that long looks like a broken app, so after a few
 * seconds this says what is happening.
 */

import { useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';

const HINT_AFTER_MS = 4000;

export function LoadingScreen() {
  const [slow, setSlow] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setSlow(true), HINT_AFTER_MS);
    return () => clearTimeout(timer);
  }, []);

  return (
    <View style={styles.container} accessibilityLabel="Loading">
      <ActivityIndicator size="large" />
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
    padding: 24,
    gap: 16,
  },
  hint: { fontSize: 14, color: '#4b5563', textAlign: 'center', maxWidth: 320 },
});
