/**
 * Session and twin state.
 *
 * Persisted state (JWT, refresh token) lives in Supabase's own storage via
 * SecureStore. This store holds only in-memory session state that Zustand
 * refreshes as auth changes.
 */

import { create } from 'zustand';

import type { ApiFailure } from '@/api/diagnostics';
import type { Twin } from '@/api/types';
import type { TwinLoadStatus } from '@/auth/route-guard';

interface SessionState {
  userId: string | null;
  email: string | null;
  twin: Twin | null;
  isReady: boolean;
  /** Progress of the post-sign-in twin fetch; see TwinLoadStatus. */
  twinStatus: TwinLoadStatus;
  /** Why the twin fetch failed, in transport terms only - never a payload. */
  twinFailure: ApiFailure | null;
  setSession: (session: { userId: string | null; email: string | null }) => void;
  setTwin: (twin: Twin | null) => void;
  setTwinStatus: (status: TwinLoadStatus, failure?: ApiFailure | null) => void;
  setReady: (v: boolean) => void;
  reset: () => void;
}

export const useSession = create<SessionState>((set) => ({
  userId: null,
  email: null,
  twin: null,
  isReady: false,
  twinStatus: 'idle',
  twinFailure: null,
  setSession: ({ userId, email }) => set({ userId, email }),
  setTwin: (twin) => set({ twin }),
  setTwinStatus: (status, failure = null) =>
    set({ twinStatus: status, twinFailure: failure }),
  setReady: (v) => set({ isReady: v }),
  reset: () =>
    set({
      userId: null,
      email: null,
      twin: null,
      twinStatus: 'idle',
      twinFailure: null,
    }),
}));
