import { goBackOr } from '../src/lib/navigation';

function fakeRouter(canGoBack: boolean) {
  const calls: string[] = [];
  return {
    calls,
    router: {
      canGoBack: () => canGoBack,
      back: () => calls.push('back'),
      replace: (href: string) => calls.push(`replace:${href}`),
    },
  };
}

describe('goBackOr', () => {
  it('goes back when there is somewhere to go back to', () => {
    const { calls, router } = fakeRouter(true);
    goBackOr(router);
    expect(calls).toEqual(['back']);
  });

  it('goes home when the screen was opened directly (refresh or link)', () => {
    // router.back() with no history does nothing, which left Cancel, Back and
    // post-save navigation stranded on the same screen.
    const { calls, router } = fakeRouter(false);
    goBackOr(router);
    expect(calls).toEqual(['replace:/(main)/home']);
  });
});
