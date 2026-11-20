/**
 * "Back" that always goes somewhere.
 *
 * `router.back()` does nothing when there is no screen underneath, which is
 * the case whenever a page was opened from a link or after a browser
 * refresh. The person then pressed Back (or saved a form that navigates
 * back) and stayed exactly where they were.
 */

interface BackCapableRouter {
  canGoBack(): boolean;
  back(): void;
  replace(href: '/(main)/home'): void;
}

export function goBackOr(router: BackCapableRouter): void {
  if (router.canGoBack()) {
    router.back();
  } else {
    router.replace('/(main)/home');
  }
}
