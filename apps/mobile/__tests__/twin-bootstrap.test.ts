/**
 * Regression tests for the post-sign-in blank page.
 *
 * The magic link restored a session correctly, but the gate then ran
 * GET /v1/twin and swallowed every failure that was not a 404. With the
 * local API down, that fetch rejects with a TypeError, so the twin stayed
 * null, the gate kept asking for the same fetch, and app/index.tsx rendered
 * its spinner forever with nothing behind it.
 *
 * These tests pin the two halves of the fix: every failure now reaches a
 * terminal state, and a failure is described without touching tokens,
 * headers or payloads.
 */

import {
  apiFailureMessage,
  describeApiFailure,
} from '@/api/diagnostics';
import { APIError } from '@/api/errors';
import { authGateAction, type TwinLoadStatus } from '@/auth/route-guard';

const SIGNED_IN = {
  isReady: true,
  hasUser: true,
  hasTwin: false,
  segment: undefined,
};

describe('authGateAction - twin bootstrap reaches a terminal state', () => {
  it('starts the fetch once from the route the magic link lands on', () => {
    expect(
      authGateAction({ ...SIGNED_IN, twinStatus: 'idle' }),
    ).toEqual({ kind: 'loadTwin' });
  });

  it('does not start a second fetch while one is in flight', () => {
    expect(
      authGateAction({ ...SIGNED_IN, twinStatus: 'loading' }),
    ).toEqual({ kind: 'wait' });
  });

  it('shows the failure instead of spinning when the fetch fails', () => {
    // THE regression: this used to produce another loadTwin (or nothing at
    // all), which is what left the root route on an endless spinner.
    expect(
      authGateAction({ ...SIGNED_IN, twinStatus: 'failed' }),
    ).toEqual({ kind: 'showError' });
  });

  it('never leaves a failed load stranded on another screen', () => {
    for (const segment of ['(auth)', '(main)']) {
      expect(
        authGateAction({ ...SIGNED_IN, twinStatus: 'failed', segment }),
      ).toEqual({ kind: 'redirect', href: '/' });
    }
  });

  it('routes a user the API has no twin for into onboarding', () => {
    expect(
      authGateAction({ ...SIGNED_IN, twinStatus: 'absent' }),
    ).toEqual({ kind: 'redirect', href: '/(onboarding)/create-twin' });
  });

  it('leaves someone already filling in the onboarding form alone', () => {
    const statuses: TwinLoadStatus[] = ['idle', 'loading', 'absent', 'failed'];
    for (const twinStatus of statuses) {
      expect(
        authGateAction({ ...SIGNED_IN, twinStatus, segment: '(onboarding)' }),
      ).toEqual({ kind: 'stay' });
    }
  });

  it('goes home once the twin is loaded, whatever the last status was', () => {
    expect(
      authGateAction({
        ...SIGNED_IN,
        hasTwin: true,
        twinStatus: 'absent',
        segment: '(onboarding)',
      }),
    ).toEqual({ kind: 'redirect', href: '/(main)/home' });
  });

  it('every state the gate can be in resolves to an action', () => {
    // Exhaustive sweep: no combination may produce loadTwin twice in a row
    // without something having changed, which is the shape of the old hang.
    const statuses: TwinLoadStatus[] = ['idle', 'loading', 'absent', 'failed'];
    const segments = [undefined, '(auth)', '(main)', '(onboarding)'];
    for (const twinStatus of statuses) {
      for (const segment of segments) {
        for (const hasTwin of [false, true]) {
          const action = authGateAction({
            isReady: true,
            hasUser: true,
            hasTwin,
            twinStatus,
            segment,
          });
          expect(action.kind).toBeDefined();
          // 'wait' is only ever legitimate while a request is in flight.
          if (action.kind === 'wait') expect(twinStatus).toBe('loading');
        }
      }
    }
  });
});

describe('describeApiFailure - classifies without leaking anything', () => {
  it('classifies an unreachable backend (the observed failure)', () => {
    // This is exactly what fetch throws when nothing is listening on :8000.
    expect(describeApiFailure(new TypeError('Failed to fetch'))).toEqual({
      kind: 'unreachable',
      status: null,
      detail: 'no response from the server',
    });
  });

  it('classifies a rejected session', () => {
    const failure = describeApiFailure(
      new APIError(401, 'unauthorized', 'Invalid token: signature failed'),
    );
    expect(failure.kind).toBe('unauthorized');
    expect(failure.status).toBe(401);
  });

  it('classifies a timeout from either side', () => {
    const abort = Object.assign(new Error('aborted'), { name: 'AbortError' });
    expect(describeApiFailure(abort).kind).toBe('timeout');
    expect(
      describeApiFailure(new APIError(408, 'timeout', 'No response.')).kind,
    ).toBe('timeout');
  });

  it('classifies 404 and 5xx distinctly', () => {
    expect(describeApiFailure(new APIError(404, 'not_found', 'x')).kind).toBe(
      'not_found',
    );
    expect(describeApiFailure(new APIError(503, 'unavailable', 'x')).kind).toBe(
      'server_error',
    );
  });

  it('falls back safely on something that is not an Error', () => {
    expect(describeApiFailure('boom').kind).toBe('unknown');
    expect(describeApiFailure(null).kind).toBe('unknown');
  });

  it('never repeats the server-supplied message', () => {
    // APIError.message is server text and can echo user input, so neither
    // the diagnostic nor the on-screen copy may contain it.
    const secretish = 'sub=11111111-2222-3333-4444-555555555555 token=abc.def';
    const failure = describeApiFailure(
      new APIError(500, 'internal', secretish, { echoed: secretish }),
    );
    const rendered = apiFailureMessage(failure, 'http://localhost:8000');
    for (const text of [failure.detail, rendered]) {
      expect(text).not.toContain(secretish);
      expect(text).not.toContain('token');
      expect(text).not.toContain('sub=');
    }
  });
});

describe('apiFailureMessage - tells the developer what to check', () => {
  it('names the API it could not reach', () => {
    const msg = apiFailureMessage(
      describeApiFailure(new TypeError('Failed to fetch')),
      'http://localhost:8000',
    );
    expect(msg).toContain('http://localhost:8000');
    expect(msg).toMatch(/backend running/i);
  });

  it('points at JWT verification when the API rejects the session', () => {
    const msg = apiFailureMessage(
      describeApiFailure(new APIError(401, 'unauthorized', 'x')),
      'http://localhost:8000',
    );
    expect(msg).toMatch(/401/);
    expect(msg).toMatch(/JWT/i);
  });

  it('still says something when there is no failure recorded', () => {
    expect(apiFailureMessage(null, 'http://localhost:8000')).toBeTruthy();
  });
});
