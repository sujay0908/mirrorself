/**
 * The small set of building blocks every screen is made of.
 *
 * Kept deliberately few: a centred page column, cards, buttons, chips, tags,
 * text fields, an avatar, empty states and notices. Screens compose these
 * instead of styling raw Views, so the app looks like one product.
 */

import { useState, type ReactElement, type ReactNode } from 'react';
import {
  ActivityIndicator,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  type RefreshControlProps,
  type StyleProp,
  type TextInputProps,
  type ViewStyle,
} from 'react-native';

import type { Tone } from '@/lib/format';
import { colors, CONTENT_MAX_WIDTH, radius, shadow, space, tones, type } from './theme';

// ---------- layout ----------

/** Centres content in a readable column on wide screens. */
export function Column({
  children,
  style,
}: {
  children: ReactNode;
  style?: StyleProp<ViewStyle>;
}) {
  return <View style={[styles.column, style]}>{children}</View>;
}

/** A scrolling page with the app background and a centred column. */
export function Page({
  children,
  refreshControl,
  contentStyle,
}: {
  children: ReactNode;
  refreshControl?: ReactElement<RefreshControlProps>;
  contentStyle?: StyleProp<ViewStyle>;
}) {
  return (
    <ScrollView
      style={styles.page}
      contentContainerStyle={[styles.pageContent, contentStyle]}
      refreshControl={refreshControl}
      keyboardShouldPersistTaps="handled"
    >
      {children}
    </ScrollView>
  );
}

/** Style for a FlatList's contentContainerStyle so it matches Page. */
export const listContent: ViewStyle = {
  width: '100%',
  maxWidth: CONTENT_MAX_WIDTH,
  alignSelf: 'center',
  padding: space.lg,
  paddingBottom: 96,
  gap: space.md,
  flexGrow: 1,
};

export function Centered({ children }: { children: ReactNode }) {
  return <View style={styles.centered}>{children}</View>;
}

export function Loading({ label = 'Loading' }: { label?: string }) {
  return (
    <View style={styles.loading} accessibilityLabel={label}>
      <ActivityIndicator color={colors.primary} />
    </View>
  );
}

// ---------- surfaces ----------

export function Card({
  children,
  onPress,
  style,
  accessibilityLabel,
}: {
  children: ReactNode;
  onPress?: () => void;
  style?: StyleProp<ViewStyle>;
  accessibilityLabel?: string;
}) {
  if (!onPress) return <View style={[styles.card, style]}>{children}</View>;
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      style={({ pressed }) => [styles.card, pressed && styles.cardPressed, style]}
    >
      {children}
    </Pressable>
  );
}

export function SectionTitle({
  children,
  action,
}: {
  children: ReactNode;
  action?: { title: string; onPress: () => void };
}) {
  return (
    <View style={styles.sectionRow}>
      <Text style={styles.sectionTitle} accessibilityRole="header">
        {children}
      </Text>
      {action ? (
        <Pressable onPress={action.onPress} accessibilityRole="button" hitSlop={8}>
          <Text style={styles.sectionAction}>{action.title}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

// ---------- buttons ----------

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';

export function Button({
  title,
  onPress,
  variant = 'primary',
  size = 'md',
  loading = false,
  disabled = false,
  style,
  accessibilityLabel,
}: {
  title: string;
  onPress: () => void;
  variant?: ButtonVariant;
  size?: 'sm' | 'md' | 'lg';
  loading?: boolean;
  disabled?: boolean;
  style?: StyleProp<ViewStyle>;
  accessibilityLabel?: string;
}) {
  const inactive = disabled || loading;
  const v = BUTTON_VARIANTS[variant];
  return (
    <Pressable
      onPress={onPress}
      disabled={inactive}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? title}
      accessibilityState={{ disabled: inactive, busy: loading }}
      style={({ pressed }) => [
        styles.button,
        size === 'sm' && styles.buttonSm,
        size === 'lg' && styles.buttonLg,
        { backgroundColor: v.bg, borderColor: v.border },
        pressed && !inactive && { backgroundColor: v.pressed },
        disabled && !loading && styles.buttonDisabled,
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator size="small" color={v.fg} />
      ) : (
        <Text
          style={[
            styles.buttonText,
            size === 'sm' && styles.buttonTextSm,
            size === 'lg' && styles.buttonTextLg,
            { color: v.fg },
          ]}
          numberOfLines={1}
        >
          {title}
        </Text>
      )}
    </Pressable>
  );
}

const BUTTON_VARIANTS: Record<
  ButtonVariant,
  { bg: string; fg: string; border: string; pressed: string }
> = {
  primary: {
    bg: colors.primary,
    fg: colors.onPrimary,
    border: colors.primary,
    pressed: colors.primaryPressed,
  },
  secondary: {
    bg: colors.surface,
    fg: colors.ink,
    border: colors.borderStrong,
    pressed: colors.surfaceAlt,
  },
  ghost: {
    bg: 'transparent',
    fg: colors.primary,
    border: 'transparent',
    pressed: colors.primarySoft,
  },
  danger: {
    bg: colors.surface,
    fg: colors.danger,
    border: '#F2C4BF',
    pressed: colors.dangerSoft,
  },
};

/** A row of buttons, right-aligned, that wraps on narrow screens. */
export function ButtonRow({
  children,
  align = 'end',
}: {
  children: ReactNode;
  align?: 'start' | 'end' | 'stretch';
}) {
  return (
    <View
      style={[
        styles.buttonRow,
        align === 'start' && { justifyContent: 'flex-start' },
        align === 'stretch' && styles.buttonRowStretch,
      ]}
    >
      {children}
    </View>
  );
}

// ---------- chips and tags ----------

export function Chip({
  label,
  selected = false,
  onPress,
}: {
  label: string;
  selected?: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityState={{ selected }}
      style={({ pressed }) => [
        styles.chip,
        selected && styles.chipSelected,
        pressed && !selected && styles.chipPressed,
      ]}
    >
      <Text style={[styles.chipText, selected && styles.chipTextSelected]}>{label}</Text>
    </Pressable>
  );
}

/** A horizontal strip of filter chips that keeps its natural height. */
export function FilterBar<T extends string>({
  options,
  value,
  onChange,
}: {
  options: ReadonlyArray<{ label: string; value: T }>;
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <View style={styles.filterWrap}>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        style={styles.filterBar}
        contentContainerStyle={styles.filterContent}
      >
        {options.map((o) => (
          <Chip
            key={o.value}
            label={o.label}
            selected={o.value === value}
            onPress={() => onChange(o.value)}
          />
        ))}
      </ScrollView>
    </View>
  );
}

export function Tag({ label, tone = 'neutral' }: { label: string; tone?: Tone }) {
  const t = tones[tone];
  return (
    <View style={[styles.tag, { backgroundColor: t.bg }]}>
      <Text style={[styles.tagText, { color: t.fg }]} numberOfLines={1}>
        {label}
      </Text>
    </View>
  );
}

export function CountBadge({ count }: { count: number }) {
  if (count <= 0) return null;
  return (
    <View style={styles.countBadge}>
      <Text style={styles.countBadgeText}>{count > 99 ? '99+' : count}</Text>
    </View>
  );
}

// ---------- identity ----------

const AVATAR_COLORS = ['#5B47E0', '#0F6E68', '#B4492F', '#2460A6', '#8A3FB8', '#1E7F55'];

export function Avatar({ name, size = 44 }: { name: string; size?: number }) {
  const initial = (name.trim().charAt(0) || '?').toUpperCase();
  const hue = AVATAR_COLORS[hash(name) % AVATAR_COLORS.length];
  return (
    <View
      style={[
        styles.avatar,
        { width: size, height: size, borderRadius: size / 2, backgroundColor: hue },
      ]}
      accessibilityElementsHidden
      importantForAccessibility="no"
    >
      <Text style={[styles.avatarText, { fontSize: size * 0.42 }]}>{initial}</Text>
    </View>
  );
}

function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i += 1) h = (h * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(h);
}

// ---------- forms ----------

export function TextField({
  label,
  hint,
  counter,
  error,
  multiline,
  style,
  ...input
}: TextInputProps & {
  label?: string;
  hint?: string;
  counter?: { value: number; max: number };
  error?: string | null;
}) {
  const [focused, setFocused] = useState(false);
  return (
    <View style={styles.field}>
      {label ? <Text style={styles.fieldLabel}>{label}</Text> : null}
      {hint ? <Text style={styles.fieldHint}>{hint}</Text> : null}
      <TextInput
        placeholderTextColor={colors.faint}
        multiline={multiline}
        {...input}
        onFocus={(e) => {
          setFocused(true);
          input.onFocus?.(e);
        }}
        onBlur={(e) => {
          setFocused(false);
          input.onBlur?.(e);
        }}
        style={[
          styles.input,
          multiline && styles.inputMultiline,
          focused && styles.inputFocused,
          error ? styles.inputError : null,
          WEB_NO_OUTLINE,
          style,
        ]}
      />
      {counter ? (
        <Text style={styles.counter}>
          {counter.value} / {counter.max}
        </Text>
      ) : null}
      {error ? <Text style={styles.fieldError}>{error}</Text> : null}
    </View>
  );
}

/** Browsers draw their own focus ring on inputs; the field draws its own. */
export const WEB_NO_OUTLINE = (Platform.OS === 'web' ? { outlineStyle: 'none' } : null) as
  | ViewStyle
  | null;

/** Big selectable option cards (style pickers, etc.). */
export function OptionGrid<T extends string>({
  options,
  value,
  onChange,
}: {
  options: ReadonlyArray<{ key: T; label: string; emoji: string; description: string }>;
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <View style={styles.optionGrid}>
      {options.map((o) => {
        const selected = o.key === value;
        return (
          <Pressable
            key={o.key}
            onPress={() => onChange(o.key)}
            accessibilityRole="radio"
            accessibilityState={{ checked: selected }}
            accessibilityLabel={`${o.label}: ${o.description}`}
            style={({ pressed }) => [
              styles.option,
              selected && styles.optionSelected,
              pressed && !selected && styles.cardPressed,
            ]}
          >
            <Text style={styles.optionEmoji}>{o.emoji}</Text>
            <Text style={[styles.optionLabel, selected && { color: colors.primaryInk }]}>
              {o.label}
            </Text>
            <Text style={styles.optionDesc}>{o.description}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

// ---------- states ----------

export function EmptyState({
  emoji,
  title,
  body,
  action,
}: {
  emoji: string;
  title: string;
  body?: string;
  action?: { title: string; onPress: () => void };
}) {
  return (
    <View style={styles.empty}>
      <View style={styles.emptyIcon}>
        <Text style={styles.emptyEmoji}>{emoji}</Text>
      </View>
      <Text style={styles.emptyTitle}>{title}</Text>
      {body ? <Text style={styles.emptyBody}>{body}</Text> : null}
      {action ? (
        <Button title={action.title} onPress={action.onPress} style={styles.emptyAction} />
      ) : null}
    </View>
  );
}

export function Notice({
  tone = 'info',
  title,
  body,
  children,
}: {
  tone?: Tone;
  title?: string;
  body?: string;
  children?: ReactNode;
}) {
  const t = tones[tone];
  return (
    <View style={[styles.notice, { backgroundColor: t.bg }]}>
      {title ? <Text style={[styles.noticeTitle, { color: t.fg }]}>{title}</Text> : null}
      {body ? <Text style={[styles.noticeBody, { color: colors.text }]}>{body}</Text> : null}
      {children}
    </View>
  );
}

/** A failed load with a reason and a way to try again. */
export function ErrorState({
  title = 'Something went wrong',
  message,
  onRetry,
}: {
  title?: string;
  message: string;
  onRetry?: () => void;
}) {
  return (
    <View style={styles.empty}>
      <View style={[styles.emptyIcon, { backgroundColor: colors.dangerSoft }]}>
        <Text style={styles.emptyEmoji}>⚠️</Text>
      </View>
      <Text style={styles.emptyTitle}>{title}</Text>
      <Text style={styles.emptyBody}>{message}</Text>
      {onRetry ? (
        <Button title="Try again" onPress={onRetry} style={styles.emptyAction} />
      ) : null}
    </View>
  );
}

// ---------- styles ----------

const styles = StyleSheet.create({
  column: { width: '100%', maxWidth: CONTENT_MAX_WIDTH, alignSelf: 'center' },
  page: { flex: 1, backgroundColor: colors.bg },
  pageContent: {
    width: '100%',
    maxWidth: CONTENT_MAX_WIDTH,
    alignSelf: 'center',
    padding: space.lg,
    paddingBottom: space.xxxl * 2,
    gap: space.md,
  },
  centered: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: space.xxl,
    backgroundColor: colors.bg,
  },
  loading: { paddingVertical: space.xxxl * 1.5, alignItems: 'center' },

  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: space.lg,
    gap: space.sm,
    ...shadow.card,
  },
  cardPressed: { backgroundColor: colors.surfaceAlt, borderColor: colors.borderStrong },

  sectionRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: space.md,
  },
  sectionTitle: { ...type.overline },
  sectionAction: { color: colors.primary, fontWeight: '600', fontSize: 13 },

  button: {
    minHeight: 44,
    paddingHorizontal: space.lg,
    borderRadius: radius.md,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  buttonSm: { minHeight: 36, paddingHorizontal: space.md, borderRadius: 10 },
  buttonLg: { minHeight: 52, paddingHorizontal: space.xl, borderRadius: radius.lg },
  buttonDisabled: { opacity: 0.45 },
  buttonText: { fontSize: 15, fontWeight: '700' },
  buttonTextSm: { fontSize: 13 },
  buttonTextLg: { fontSize: 16 },
  buttonRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'flex-end',
    gap: space.sm,
  },
  buttonRowStretch: { justifyContent: 'flex-start' },

  chip: {
    paddingHorizontal: 14,
    paddingVertical: 7,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  chipSelected: { backgroundColor: colors.ink, borderColor: colors.ink },
  chipPressed: { backgroundColor: colors.surfaceAlt },
  chipText: { fontSize: 13, fontWeight: '600', color: colors.text },
  chipTextSelected: { color: colors.surface },
  filterWrap: { width: '100%', maxWidth: CONTENT_MAX_WIDTH, alignSelf: 'center' },
  filterBar: { flexGrow: 0, flexShrink: 0 },
  filterContent: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.sm,
    paddingHorizontal: space.lg,
    paddingTop: space.sm,
    paddingBottom: space.xs,
  },

  tag: {
    alignSelf: 'flex-start',
    paddingHorizontal: 9,
    paddingVertical: 3,
    borderRadius: radius.pill,
  },
  tagText: { fontSize: 12, fontWeight: '700' },
  countBadge: {
    minWidth: 22,
    height: 22,
    paddingHorizontal: 6,
    borderRadius: 11,
    backgroundColor: colors.danger,
    alignItems: 'center',
    justifyContent: 'center',
  },
  countBadgeText: { color: '#FFFFFF', fontSize: 12, fontWeight: '800' },

  avatar: { alignItems: 'center', justifyContent: 'center' },
  avatarText: { color: '#FFFFFF', fontWeight: '800' },

  field: { gap: 6 },
  fieldLabel: { fontSize: 14, fontWeight: '700', color: colors.ink },
  fieldHint: { ...type.small, marginTop: -2 },
  input: {
    backgroundColor: colors.surface,
    borderWidth: 1.5,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 16,
    color: colors.ink,
  },
  inputMultiline: { minHeight: 110, textAlignVertical: 'top' },
  inputFocused: { borderColor: colors.primary },
  inputError: { borderColor: colors.danger },
  counter: { ...type.caption, textAlign: 'right' },
  fieldError: { fontSize: 13, color: colors.danger },

  optionGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm },
  option: {
    flexGrow: 1,
    flexBasis: 150,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1.5,
    borderColor: colors.border,
    padding: 14,
    gap: 2,
  },
  optionSelected: { borderColor: colors.primary, backgroundColor: colors.primarySoft },
  optionEmoji: { fontSize: 22, marginBottom: 4 },
  optionLabel: { fontSize: 15, fontWeight: '700', color: colors.ink },
  optionDesc: { ...type.small },

  empty: { alignItems: 'center', paddingVertical: space.xxxl * 1.5, paddingHorizontal: space.xxl },
  emptyIcon: {
    width: 72,
    height: 72,
    borderRadius: 36,
    backgroundColor: colors.primarySoft,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: space.lg,
  },
  emptyEmoji: { fontSize: 32 },
  emptyTitle: { ...type.title, textAlign: 'center' },
  emptyBody: { ...type.body, color: colors.muted, textAlign: 'center', marginTop: 6, maxWidth: 380 },
  emptyAction: { marginTop: space.xl },

  notice: { borderRadius: radius.md, padding: 14, gap: 4 },
  noticeTitle: { fontSize: 14, fontWeight: '700' },
  noticeBody: { fontSize: 14, lineHeight: 20 },
});
