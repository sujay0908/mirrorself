/**
 * What to tell a person when an action fails.
 *
 * Copy is chosen from the error's stable `code` and HTTP status only. The
 * server's own message is never shown: it is written for developers and can
 * quote what the user typed back at them.
 *
 * Pure (no react-native imports) so it runs in the node test environment.
 */

import { APIError } from '@/api/errors';

const BY_CODE: Record<string, string> = {
  // AI path
  llm_provider_not_configured:
    "Your Twin can't reply yet because the AI service hasn't been set up. Your message was not sent.",
  llm_provider_misconfigured:
    "Your Twin can't reply right now because of a configuration problem on our side. Your message was not sent.",
  llm_rate_limited: 'The AI service is busy. Wait a few seconds and try again.',
  llm_timeout: 'The AI took too long to answer. Try again; your message will not be sent twice.',
  llm_unavailable: 'The AI service is temporarily unavailable. Try again in a moment.',
  llm_refused: 'Your Twin declined to answer that message. Try putting it another way.',
  llm_empty_response: 'Your Twin came back with an empty reply. Try again.',
  llm_request_rejected: 'The AI service could not process that message.',
  llm_provider_error: 'The AI service could not process that message.',
  message_in_progress: 'Still working on your previous message…',

  // Limits
  rate_limited: "You're going a bit fast. Wait a few seconds and try again.",
  payload_too_large: 'That is too long to send.',

  // Availability
  server_busy: 'The service is busy right now. Try again in a moment.',
  database_unavailable: 'The service is having trouble right now. Try again in a moment.',
  dependency_timeout: 'The service is slow to respond right now. Try again in a moment.',
  service_unavailable: 'The service is temporarily unavailable. Try again in a moment.',
  auth_unavailable: "We couldn't verify your sign-in just now. Try again in a moment.",

  // Domain
  validation_error: "Some of what you entered isn't valid. Check it and try again.",
  goal_validation_error: "Some of what you entered isn't valid. Check it and try again.",
  invalid_goal_status_transition: "A goal can't move to that status from where it is now.",
  twin_already_exists: 'You already have a Twin.',
  twin_not_found: "You don't have a Twin yet.",
  conversation_not_found: "This conversation doesn't exist or isn't yours.",
  memory_not_found: "This memory doesn't exist any more.",
  memory_candidate_not_found: 'This suggestion is no longer available.',
  memory_candidate_already_resolved: 'This suggestion was already handled.',
  reflection_not_found: 'This reflection is no longer available.',
  reflection_already_resolved: 'This reflection was already handled.',
  reflection_apply_error: 'The reflection was confirmed but could not be applied.',
  goal_not_found: "This goal doesn't exist or isn't yours.",
};

function isAbort(err: unknown): boolean {
  return (
    typeof err === 'object' &&
    err !== null &&
    'name' in err &&
    (err as { name?: unknown }).name === 'AbortError'
  );
}

export function userErrorMessage(err: unknown): string {
  if (err instanceof APIError) {
    const known = BY_CODE[err.code];
    if (known) return known;
    const { status } = err;
    if (status === 401) return 'Your session has expired. Sign in again.';
    if (status === 403) return "You don't have access to that.";
    if (status === 404) return "That doesn't exist or isn't yours.";
    if (status === 408) return "The server didn't answer in time. Check your connection and try again.";
    if (status === 409) return 'That conflicts with another change. Refresh and try again.';
    if (status === 413) return BY_CODE.payload_too_large;
    if (status === 422) return BY_CODE.validation_error;
    if (status === 429) return BY_CODE.rate_limited;
    if (status >= 500) {
      return `Something went wrong on our side (HTTP ${status}). Try again in a moment.`;
    }
    return "That request wasn't accepted. Check what you entered and try again.";
  }
  if (isAbort(err)) return "The server didn't answer in time. Try again.";
  // fetch rejects with a TypeError when the network or CORS stops the request.
  if (err instanceof TypeError) {
    return "Can't reach the server. Check your connection and try again.";
  }
  return 'Something went wrong. Please try again.';
}

/** Whether trying the same request again could succeed without any change. */
export function isRetryable(err: unknown): boolean {
  if (err instanceof APIError) {
    if (err.code === 'llm_provider_not_configured') return false;
    if (err.code === 'llm_provider_misconfigured') return false;
    return err.status === 408 || err.status === 409 || err.status === 429 || err.status >= 500;
  }
  return isAbort(err) || err instanceof TypeError;
}

/** Seconds the server asked us to wait, when it said. */
export function retryAfterSeconds(err: unknown): number | null {
  if (!(err instanceof APIError)) return null;
  const value = err.details?.retry_after_seconds;
  return typeof value === 'number' && value > 0 ? value : null;
}
