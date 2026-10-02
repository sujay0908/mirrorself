/**
 * One-time onboarding: name the twin and pick a communication style.
 */

import { useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { useRouter } from 'expo-router';

import { api } from '@/api/client';
import type { CommunicationStylePreset } from '@/api/types';
import { useSession } from '@/state/session';

const styles_options: { key: CommunicationStylePreset; label: string }[] = [
  { key: 'neutral', label: 'Neutral' },
  { key: 'terse', label: 'Terse' },
  { key: 'warm', label: 'Warm' },
  { key: 'analytical', label: 'Analytical' },
];

export default function CreateTwinScreen() {
  const router = useRouter();
  const setTwin = useSession((s) => s.setTwin);
  const [name, setName] = useState('');
  const [style, setStyle] = useState<CommunicationStylePreset>('neutral');
  const [loading, setLoading] = useState(false);

  async function onSubmit() {
    if (!name.trim()) {
      Alert.alert('Please give your twin a name.');
      return;
    }
    setLoading(true);
    try {
      const twin = await api.createTwin({ name, communication_style: style });
      setTwin(twin);
      router.replace('/(main)/home');
    } catch (err) {
      Alert.alert('Could not create twin', String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Create your Twin</Text>
      <Text style={styles.label}>Twin name</Text>
      <TextInput
        style={styles.input}
        placeholder="Aurora, Nova, Ada …"
        value={name}
        onChangeText={setName}
        editable={!loading}
      />
      <Text style={styles.label}>Communication style</Text>
      <View style={styles.row}>
        {styles_options.map((opt) => (
          <Pressable
            key={opt.key}
            onPress={() => setStyle(opt.key)}
            style={[styles.chip, style === opt.key && styles.chipActive]}
          >
            <Text
              style={style === opt.key ? styles.chipActiveText : styles.chipText}
            >
              {opt.label}
            </Text>
          </Pressable>
        ))}
      </View>
      {loading ? (
        <ActivityIndicator />
      ) : (
        <Pressable onPress={onSubmit} style={styles.button}>
          <Text style={styles.buttonText}>Create Twin</Text>
        </Pressable>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 24, gap: 12, justifyContent: 'center' },
  title: { fontSize: 24, fontWeight: '700' },
  label: { fontSize: 14, fontWeight: '600', marginTop: 12 },
  input: {
    borderWidth: 1,
    borderColor: '#d1d5db',
    padding: 12,
    borderRadius: 8,
  },
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: {
    borderWidth: 1,
    borderColor: '#d1d5db',
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 999,
  },
  chipActive: { backgroundColor: '#4f46e5', borderColor: '#4f46e5' },
  chipText: { color: '#111827' },
  chipActiveText: { color: '#ffffff' },
  button: {
    marginTop: 12,
    backgroundColor: '#111827',
    padding: 14,
    borderRadius: 8,
    alignItems: 'center',
  },
  buttonText: { color: '#ffffff', fontWeight: '600' },
});
