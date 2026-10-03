/**
 * New goal screen (Sprint 4, DF6).
 *
 * Minimal form: title (required), optional description, optional priority
 * (1..5, default 3). Target date is deferred to the detail-edit screen so
 * this flow stays frictionless on mobile.
 */

import { useState } from 'react';
import {
  Alert,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { Stack, useRouter } from 'expo-router';

import { api, APIError } from '@/api/client';

const PRIORITIES = [1, 2, 3, 4, 5];

export default function NewGoalScreen() {
  const router = useRouter();
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [priority, setPriority] = useState(3);
  const [saving, setSaving] = useState(false);

  async function save() {
    const trimmed = title.trim();
    if (!trimmed) {
      Alert.alert('A title is required.');
      return;
    }
    setSaving(true);
    try {
      const goal = await api.createGoal({
        title: trimmed,
        description: description.trim() || null,
        priority,
      });
      router.replace({
        pathname: '/(main)/goals/[id]',
        params: { id: goal.id },
      });
    } catch (e) {
      Alert.alert(
        'Could not create goal',
        e instanceof APIError ? e.message : String(e),
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <Stack.Screen options={{ title: 'New goal' }} />
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.label}>Title</Text>
        <TextInput
          value={title}
          onChangeText={setTitle}
          placeholder="Ship Sprint 4"
          style={styles.input}
          maxLength={200}
        />

        <Text style={styles.label}>Description (optional)</Text>
        <TextInput
          value={description}
          onChangeText={setDescription}
          placeholder="Why this matters, how you'll know you're done…"
          style={[styles.input, styles.multiline]}
          multiline
          maxLength={4000}
        />

        <Text style={styles.label}>Priority (1 highest)</Text>
        <View style={styles.priorityRow}>
          {PRIORITIES.map((p) => (
            <Pressable
              key={p}
              onPress={() => setPriority(p)}
              style={[
                styles.priorityChip,
                priority === p && styles.priorityChipActive,
              ]}
            >
              <Text
                style={[
                  styles.priorityText,
                  priority === p && styles.priorityTextActive,
                ]}
              >
                {p}
              </Text>
            </Pressable>
          ))}
        </View>

        <Pressable
          onPress={save}
          disabled={saving || !title.trim()}
          style={[
            styles.btn,
            (!title.trim() || saving) && styles.btnDisabled,
          ]}
        >
          <Text style={styles.btnText}>{saving ? '…' : 'Create goal'}</Text>
        </Pressable>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#f9fafb' },
  content: { padding: 16, gap: 12 },
  label: { fontSize: 13, color: '#374151', fontWeight: '600', marginTop: 8 },
  input: {
    backgroundColor: '#ffffff',
    borderWidth: 1,
    borderColor: '#d1d5db',
    borderRadius: 12,
    padding: 12,
    fontSize: 16,
  },
  multiline: { minHeight: 100, textAlignVertical: 'top' },
  priorityRow: { flexDirection: 'row', gap: 8 },
  priorityChip: {
    width: 44,
    height: 44,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: '#d1d5db',
    backgroundColor: '#ffffff',
    alignItems: 'center',
    justifyContent: 'center',
  },
  priorityChipActive: {
    borderColor: '#4338ca',
    backgroundColor: '#eef2ff',
  },
  priorityText: { color: '#374151', fontWeight: '700' },
  priorityTextActive: { color: '#4338ca' },
  btn: {
    marginTop: 24,
    backgroundColor: '#4f46e5',
    paddingVertical: 14,
    borderRadius: 12,
    alignItems: 'center',
  },
  btnDisabled: { backgroundColor: '#9ca3af' },
  btnText: { color: '#ffffff', fontWeight: '700', fontSize: 15 },
});
