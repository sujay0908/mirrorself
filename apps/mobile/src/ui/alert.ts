/**
 * `Alert.alert` that also works in the browser.
 *
 * React Native Web ships `Alert` as an empty stub, so on the web build every
 * validation message, error report and confirmation in the app silently did
 * nothing: an invalid email on the sign-in screen, a failed save, the
 * "Delete memory?" prompt. Screens import `Alert` from here instead of from
 * react-native and keep their call sites unchanged.
 *
 * On the web a plain message uses `window.alert`; a message with a cancel
 * button and an action uses `window.confirm`, which is the same choice.
 */

import { Alert as NativeAlert, Platform, type AlertButton } from 'react-native';

function webAlert(title: string, message?: string, buttons?: AlertButton[]): void {
  if (typeof window === 'undefined') return;
  const text = message ? `${title}\n\n${message}` : title;
  if (!buttons || buttons.length <= 1) {
    window.alert(text);
    buttons?.[0]?.onPress?.();
    return;
  }
  const cancel = buttons.find((b) => b.style === 'cancel');
  const actions = buttons.filter((b) => b !== cancel);
  const chosen = window.confirm(text) ? actions[actions.length - 1] : cancel;
  chosen?.onPress?.();
}

export const Alert = {
  alert(title: string, message?: string, buttons?: AlertButton[]): void {
    if (Platform.OS === 'web') {
      webAlert(title, message, buttons);
      return;
    }
    NativeAlert.alert(title, message, buttons);
  },
};
