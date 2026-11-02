/**
 * Supabase client, with Expo SecureStore as the JWT persistence layer so the
 * access token survives cold-starts but is never in AsyncStorage plaintext.
 */

import 'react-native-url-polyfill/auto';
import { createClient, type SupportedStorage } from '@supabase/supabase-js';
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

import { config } from '@/config';

const secureStorage: SupportedStorage = {
  async getItem(key) {
    return SecureStore.getItemAsync(key);
  },
  async setItem(key, value) {
    await SecureStore.setItemAsync(key, value);
  },
  async removeItem(key) {
    await SecureStore.deleteItemAsync(key);
  },
};

// expo-secure-store ships no web implementation (its web module is an empty
// object), so SecureStore.* rejects in the browser and would leave the auth
// bootstrap hanging. Use localStorage on web; native keeps SecureStore.
const webStorage: SupportedStorage = {
  async getItem(key) {
    if (typeof localStorage === 'undefined') return null;
    return localStorage.getItem(key);
  },
  async setItem(key, value) {
    if (typeof localStorage === 'undefined') return;
    localStorage.setItem(key, value);
  },
  async removeItem(key) {
    if (typeof localStorage === 'undefined') return;
    localStorage.removeItem(key);
  },
};

export const supabase = createClient(config.supabaseUrl, config.supabaseAnonKey, {
  auth: {
    storage: Platform.OS === 'web' ? webStorage : secureStorage,
    autoRefreshToken: true,
    persistSession: true,
    // Web: the magic-link callback returns the session in the URL (implicit
    // flow puts it in the hash fragment). supabase-js only reads it when this
    // is enabled; left off, the tokens are ignored and the auth gate bounces
    // back to /login. Native has no such URL, so it keeps the old behavior.
    detectSessionInUrl: Platform.OS === 'web',
  },
});

export type SupabaseClient = typeof supabase;
