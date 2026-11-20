/**
 * MirrorSelf design tokens.
 *
 * Calm and personal: warm paper background, white cards, one indigo brand
 * colour, soft tinted tags. Every screen takes its colours, spacing and type
 * from here; nothing else should hard-code a hex value.
 */

import type { TextStyle, ViewStyle } from 'react-native';

import type { Tone } from '@/lib/format';

export const colors = {
  bg: '#F6F4F0',
  surface: '#FFFFFF',
  surfaceAlt: '#FAF8F5',
  border: '#E9E4DC',
  borderStrong: '#D7D0C5',

  ink: '#1E1B2E',
  text: '#3B3649',
  muted: '#6F6880',
  faint: '#A49EB1',

  primary: '#5B47E0',
  primaryPressed: '#4936C8',
  primarySoft: '#EEEBFD',
  primaryBorder: '#DCD5FB',
  primaryInk: '#3A2AA6',
  onPrimary: '#FFFFFF',

  danger: '#C2362D',
  dangerSoft: '#FDECEA',
  success: '#1E7F55',
  successSoft: '#E4F4EB',
  warning: '#9A5B0E',
  warningSoft: '#FCF0DC',
  info: '#2460A6',
  infoSoft: '#E5EEF9',
  teal: '#0F6E68',
  tealSoft: '#DFF3F0',
  tealBorder: '#BFE6E0',
} as const;

export const tones: Record<Tone, { bg: string; fg: string }> = {
  primary: { bg: colors.primarySoft, fg: colors.primaryInk },
  success: { bg: colors.successSoft, fg: colors.success },
  warning: { bg: colors.warningSoft, fg: colors.warning },
  info: { bg: colors.infoSoft, fg: colors.info },
  teal: { bg: colors.tealSoft, fg: colors.teal },
  neutral: { bg: '#F0EDE8', fg: colors.muted },
  danger: { bg: colors.dangerSoft, fg: colors.danger },
};

export const space = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  xxl: 24,
  xxxl: 32,
} as const;

export const radius = {
  sm: 8,
  md: 12,
  lg: 16,
  xl: 22,
  pill: 999,
} as const;

/** Content never stretches wider than this on a desktop browser. */
export const CONTENT_MAX_WIDTH = 720;

export const type = {
  display: {
    fontSize: 28,
    lineHeight: 34,
    fontWeight: '800',
    letterSpacing: -0.5,
    color: colors.ink,
  },
  title: { fontSize: 20, lineHeight: 26, fontWeight: '700', color: colors.ink },
  heading: { fontSize: 16, lineHeight: 22, fontWeight: '700', color: colors.ink },
  body: { fontSize: 15, lineHeight: 22, color: colors.text },
  bodyStrong: { fontSize: 15, lineHeight: 22, fontWeight: '600', color: colors.ink },
  small: { fontSize: 13, lineHeight: 18, color: colors.muted },
  caption: { fontSize: 12, lineHeight: 16, color: colors.muted },
  overline: {
    fontSize: 11,
    lineHeight: 14,
    fontWeight: '700',
    letterSpacing: 0.8,
    textTransform: 'uppercase',
    color: colors.muted,
  },
} satisfies Record<string, TextStyle>;

export const shadow = {
  card: {
    shadowColor: '#1E1B2E',
    shadowOpacity: 0.05,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 2 },
    elevation: 1,
  },
  raised: {
    shadowColor: '#1E1B2E',
    shadowOpacity: 0.12,
    shadowRadius: 18,
    shadowOffset: { width: 0, height: 6 },
    elevation: 4,
  },
} satisfies Record<string, ViewStyle>;

/** Shared options for every stack header. */
export const headerOptions = {
  headerStyle: { backgroundColor: colors.bg },
  headerShadowVisible: false,
  headerTintColor: colors.primary,
  headerTitleStyle: { color: colors.ink, fontWeight: '700' as const, fontSize: 17 },
  headerBackTitleVisible: false,
  contentStyle: { backgroundColor: colors.bg },
};
