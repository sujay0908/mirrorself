/**
 * Session and twin state.
 *
 * Persisted state (JWT, refresh token) lives in Supabase's own storage via
 * SecureStore. This store holds only in-memory session state that Zustand
 * refreshes as auth changes.
 */

import { create } from 'zustand';

import type { Twin } from '@/api/types';

interface SessionState {
  userId: string | null;
  email: string | null;
  twin: Twin | null;
  isReady: boolean;
  setSession: (session: { userId: string | null; email: string | null }) => void;
  setTwin: (twin: Twin | null) => void;
  setReady: (v: boolean) => void;
  reset: () => void;
}

export const useSession = create<SessionState>((set) => ({
  userId: null,
  email: null,
  twin: null,
  isReady: false,
  setSession: ({ userId, email }) => set({ userId, email }),
  setTwin: (twin) => set({ twin }),
  setReady: (v) => set({ isReady: v }),
  reset: () => set({ userId: null, email: null, twin: null }),
}));
