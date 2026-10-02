/**
 * Minimal magic-link sign-in.
 *
 * Sprint 1 uses Supabase's OTP via email; a "we sent you a link" screen is
 * intentional — social sign-in is a Sprint 4+ item.
 */

import { useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Button,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import { supabase } from '@/auth/supabase';

export default function LoginScreen() {
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);

  async function onSubmit() {
    if (!email.includes('@')) {
      Alert.alert('Please enter a valid email.');
      return;
    }
    setLoading(true);
    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: { shouldCreateUser: true },
    });
    setLoading(false);
    if (error) {
      Alert.alert('Sign-in error', error.message);
      return;
    }
    setSent(true);
  }

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Personal AI Twin</Text>
      <Text style={styles.subtitle}>
        The avatar is the interface; the intelligence is the product.
      </Text>
      <TextInput
        style={styles.input}
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="email-address"
        placeholder="you@example.com"
        value={email}
        onChangeText={setEmail}
        editable={!loading && !sent}
      />
      {loading ? (
        <ActivityIndicator />
      ) : sent ? (
        <Text style={styles.info}>
          Check your email — we sent you a sign-in link.
        </Text>
      ) : (
        <Button title="Send sign-in link" onPress={onSubmit} />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    padding: 24,
    justifyContent: 'center',
    gap: 16,
  },
  title: { fontSize: 28, fontWeight: '700' },
  subtitle: { fontSize: 15, color: '#4b5563' },
  input: {
    borderWidth: 1,
    borderColor: '#d1d5db',
    padding: 12,
    borderRadius: 8,
  },
  info: { color: '#059669' },
});
