/**
 * Root route - the _layout's auth gate redirects to the correct stack.
 *
 * This screen renders briefly during that redirect, so it is also the one
 * place a user sees if the gate cannot finish. When the post-sign-in twin
 * fetch fails terminally it says why and offers a retry, instead of showing
 * a spinner that will never resolve.
 */

import { apiFailureMessage } from '@/api/diagnostics';
import { LoadingScreen } from '@/components/LoadingScreen';
import { config } from '@/config';
import { useSession } from '@/state/session';
import { Centered, ErrorState } from '@/ui/kit';

export default function Index() {
  const twinStatus = useSession((s) => s.twinStatus);
  const twinFailure = useSession((s) => s.twinFailure);
  const setTwinStatus = useSession((s) => s.setTwinStatus);

  if (twinStatus === 'failed') {
    return (
      <Centered>
        <ErrorState
          title="Could not load your Twin"
          message={apiFailureMessage(twinFailure, config.apiUrl)}
          // Back to 'idle' is all a retry needs: the gate re-runs the fetch.
          onRetry={() => setTwinStatus('idle')}
        />
      </Centered>
    );
  }

  return <LoadingScreen />;
}
