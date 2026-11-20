import {
  confidenceLabel,
  formatProfileValue,
  friendlyEvent,
  goalStatus,
  greeting,
  humanizeKey,
  importanceLabel,
  memoryType,
  plural,
  priorityLabel,
  profileFieldLabel,
  reflectionRunMessage,
  relativeTime,
  styleInfo,
} from '../src/lib/format';

describe('relativeTime', () => {
  const now = new Date(2026, 10, 20, 20, 0, 0); // Fri Nov 20 2026, 8 PM local

  it('reads naturally for recent moments', () => {
    expect(relativeTime(new Date(2026, 10, 20, 19, 59, 30).toISOString(), now)).toBe('just now');
    expect(relativeTime(new Date(2026, 10, 20, 19, 45).toISOString(), now)).toBe('15 min ago');
    expect(relativeTime(new Date(2026, 10, 20, 9, 0).toISOString(), now)).toBe('11 h ago');
  });

  it('uses day words, then dates', () => {
    expect(relativeTime(new Date(2026, 10, 19, 23, 0).toISOString(), now)).toBe('Yesterday');
    expect(relativeTime(new Date(2026, 10, 16, 12, 0).toISOString(), now)).toBe('Mon');
    expect(relativeTime(new Date(2026, 10, 3, 12, 0).toISOString(), now)).toBe('Nov 3');
    expect(relativeTime(new Date(2025, 10, 3, 12, 0).toISOString(), now)).toBe('Nov 3, 2025');
  });

  it('never throws on bad input', () => {
    expect(relativeTime('not a date', now)).toBe('');
  });
});

describe('greeting', () => {
  it('follows the time of day', () => {
    expect(greeting(new Date(2026, 0, 1, 8))).toBe('Good morning');
    expect(greeting(new Date(2026, 0, 1, 14))).toBe('Good afternoon');
    expect(greeting(new Date(2026, 0, 1, 21))).toBe('Good evening');
    expect(greeting(new Date(2026, 0, 1, 2))).toBe('Up late');
  });
});

describe('scores in words', () => {
  it('replaces "conf 0.80 · imp 0.60"', () => {
    expect(confidenceLabel(0.8)).toBe('Sure about this');
    expect(confidenceLabel(0.6)).toBe('Fairly sure');
    expect(confidenceLabel(0.2)).toBe('A guess');
    expect(importanceLabel(0.9)).toBe('Important');
    expect(importanceLabel(0.6)).toBe('Worth knowing');
    expect(importanceLabel(0.1)).toBe('Minor detail');
  });
});

describe('labels', () => {
  it('names memory types, goal states, priorities and styles', () => {
    expect(memoryType('PREFERENCE').label).toBe('Preference');
    expect(memoryType('SOMETHING_NEW').label).toBe('Memory');
    expect(goalStatus('abandoned').label).toBe('Dropped');
    expect(priorityLabel(1)).toBe('Top');
    expect(priorityLabel(3)).toBe('Medium');
    expect(priorityLabel(42)).toBe('Medium');
    expect(styleInfo('terse').label).toBe('Brief');
    expect(plural(1, 'memory', 'memories')).toBe('1 memory');
    expect(plural(3, 'memory', 'memories')).toBe('3 memories');
  });

  it('never shows raw profile field names', () => {
    expect(profileFieldLabel('communication_style_notes')).toBe('How your Twin talks to you');
    expect(profileFieldLabel('basic_profile')).toBe('The basics about you');
    expect(humanizeKey('home_city')).toBe('Home city');
  });
});

describe('formatProfileValue', () => {
  it('writes values the way people would', () => {
    expect(formatProfileValue(null)).toBe('Nothing yet');
    expect(formatProfileValue('')).toBe('Nothing yet');
    expect(formatProfileValue('Short replies')).toBe('Short replies');
    expect(formatProfileValue({ city: 'Bengaluru', home_town: 'Mysuru' })).toBe(
      'City: Bengaluru\nHome town: Mysuru',
    );
    expect(formatProfileValue({})).toBe('Nothing yet');
  });
});

describe('friendlyEvent', () => {
  it('turns audit strings into sentences', () => {
    expect(
      friendlyEvent('memory_learned', 'PREFERENCE memory learned via confirmed candidate').title,
    ).toBe('A new preference about you');
    expect(
      friendlyEvent(
        'profile_confirmed',
        'profile.communication_style_notes updated via confirmed reflection',
      ).title,
    ).toBe('How you like it to talk to you');
    expect(friendlyEvent('profile_confirmed', '', 'basic_profile').title).toBe(
      'More of the basics about you',
    );
  });

  it('keeps insights as acknowledgements, not learning', () => {
    const e = friendlyEvent('insight_acknowledged', 'insight acknowledged (no memory or profile change)');
    expect(e.lead).toBe('acknowledged');
    expect(e.leadText).toBe('You acknowledged');
  });

  it('handles unknown events', () => {
    expect(friendlyEvent('something_else').title).toBe('Something changed');
  });
});

describe('reflectionRunMessage', () => {
  it('never shows an internal error code', () => {
    const m = reflectionRunMessage({ candidates_persisted: 0, error: 'parse_error' });
    expect(m.body).not.toContain('parse_error');
  });

  it('says how many new thoughts there are', () => {
    expect(reflectionRunMessage({ candidates_persisted: 2, error: null }).body).toBe(
      '2 new thoughts to look at.',
    );
  });
});
