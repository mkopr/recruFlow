import { beforeEach, describe, expect, it } from 'vitest';

import { loadScoreAlertPrefs, saveScoreAlertPrefs } from './scoreAlertPrefs';

const STORAGE_KEY = 'recruflow.scoreAlertPrefs';

beforeEach(() => {
  localStorage.clear();
});

describe('loadScoreAlertPrefs', () => {
  it('returns defaults when nothing is stored', () => {
    expect(loadScoreAlertPrefs()).toEqual({
      sound: 'chime',
      volume: 0.5,
      muted: false,
      minScorePercent: 90,
    });
  });

  it('falls back to defaults on malformed stored JSON', () => {
    localStorage.setItem(STORAGE_KEY, 'not json {{{');

    expect(loadScoreAlertPrefs()).toEqual({
      sound: 'chime',
      volume: 0.5,
      muted: false,
      minScorePercent: 90,
    });
  });

  it('falls back to defaults when minScorePercent is missing (pre-migration shape)', () => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ sound: 'chime', volume: 0.5, muted: false }),
    );

    expect(loadScoreAlertPrefs()).toEqual({
      sound: 'chime',
      volume: 0.5,
      muted: false,
      minScorePercent: 90,
    });
  });
});

describe('saveScoreAlertPrefs', () => {
  it('round-trips exactly what was saved', () => {
    const prefs = { sound: 'arpeggio' as const, volume: 0.8, muted: true, minScorePercent: 75 };

    saveScoreAlertPrefs(prefs);

    expect(loadScoreAlertPrefs()).toEqual(prefs);
  });
});
