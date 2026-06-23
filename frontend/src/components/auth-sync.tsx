"use client";

import { useEffect } from "react";
import { useAuth } from "@/lib/auth-store";
import { me } from "@/lib/api";
import { supabase } from "@/lib/supabase/client";

export function AuthSync() {
  const { token, setSession, logout } = useAuth();

  useEffect(() => {
    let cancelled = false;

    async function syncFromSession(accessToken?: string | null) {
      if (!accessToken) {
        if (!cancelled) logout();
        return;
      }

      try {
        const user = await me(accessToken);
        if (!cancelled) setSession(accessToken, user);
      } catch {
        if (!cancelled) logout();
      }
    }

    supabase.auth.getSession().then(({ data }) => {
      const accessToken = data.session?.access_token;
      if (accessToken && accessToken !== token) {
        void syncFromSession(accessToken);
      }
    });

    const { data } = supabase.auth.onAuthStateChange((_event, session) => {
      void syncFromSession(session?.access_token);
    });

    return () => {
      cancelled = true;
      data.subscription.unsubscribe();
    };
  }, [logout, setSession, token]);

  return null;
}
