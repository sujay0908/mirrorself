"use client";
import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { UserPrivate } from "./api";

type AuthState = {
  token: string | null;
  user: UserPrivate | null;
  setSession: (token: string, user: UserPrivate) => void;
  setUser: (user: UserPrivate) => void;
  logout: () => void;
};

export const useAuth = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      setSession: (token, user) => set({ token, user }),
      setUser: (user) => set({ user }),
      logout: () => set({ token: null, user: null }),
    }),
    { name: "mirrorself.auth" }
  )
);
