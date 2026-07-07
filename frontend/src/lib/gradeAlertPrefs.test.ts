import { beforeEach, describe, expect, it } from 'vitest';

import { loadGradeAlertPrefs, saveGradeAlertPrefs } from './gradeAlertPrefs';

const STORAGE_KEY = 'recruflow.gradeAlertPrefs';

beforeEach(() => {
  localStorage.clear();
});

describe('loadGradeAlertPrefs', () => {
  it('returns defaults when nothing is stored', () => {
    expect(loadGradeAlertPrefs()).toEqual({ sound: 'chime', volume: 0.5, muted: false });
  });

  it('falls back to defaults on malformed stored JSON', () => {
    localStorage.setItem(STORAGE_KEY, 'not json {{{');

    expect(loadGradeAlertPrefs()).toEqual({ sound: 'chime', volume: 0.5, muted: false });
  });
});

describe('saveGradeAlertPrefs', () => {
  it('round-trips exactly what was saved', () => {
    const prefs = { sound: 'arpeggio' as const, volume: 0.8, muted: true };

    saveGradeAlertPrefs(prefs);

    expect(loadGradeAlertPrefs()).toEqual(prefs);
  });
});
