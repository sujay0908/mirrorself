/**
 * Re-load a screen's data when the person comes back to it.
 *
 * Screens in a stack stay mounted underneath the one on top, so a list that
 * loaded once kept showing what it loaded: a deleted memory, an old title,
 * no sign of the chat you just had. This runs `refresh` every time the
 * screen regains focus, except the first time (the screen's own initial load
 * covers that). Failures are ignored on purpose: the screen keeps showing
 * what it already has rather than replacing it with an error.
 */

import { useFocusEffect } from 'expo-router';
import { useCallback, useRef } from 'react';

export function useRefreshOnFocus(refresh: () => unknown): void {
  const latest = useRef(refresh);
  latest.current = refresh;
  const first = useRef(true);

  useFocusEffect(
    useCallback(() => {
      if (first.current) {
        first.current = false;
        return;
      }
      Promise.resolve()
        .then(() => latest.current())
        .catch(() => undefined);
    }, []),
  );
}
