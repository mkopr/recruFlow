import { beforeEach, describe, expect, it } from 'vitest';

import { defaultOfferListPrefs, loadOfferListPrefs, saveOfferListPrefs } from './offerListPrefs';

const STORAGE_KEY = 'recruflow.offerListPrefs';

beforeEach(() => {
  localStorage.clear();
});

describe('loadOfferListPrefs', () => {
  it('returns defaults (not-applied-only, empty filters) when nothing is stored', () => {
    expect(loadOfferListPrefs()).toEqual(defaultOfferListPrefs());
    expect(loadOfferListPrefs().filters.showApplied).toBe(false);
  });

  it('falls back to defaults on malformed stored JSON', () => {
    localStorage.setItem(STORAGE_KEY, 'not json {{{');

    expect(loadOfferListPrefs()).toEqual(defaultOfferListPrefs());
  });

  it('falls back to defaults when sort.orderBy is not a recognised value', () => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        filters: {},
        minScore: '',
        sort: { orderBy: 'bogus', order: 'desc' },
      }),
    );

    expect(loadOfferListPrefs()).toEqual(defaultOfferListPrefs());
  });

  it('falls back to defaults when a filter field has the wrong type', () => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        filters: { minSalary: 'not-a-number' },
        minScore: '',
        sort: { orderBy: 'posted_at', order: 'desc' },
      }),
    );

    expect(loadOfferListPrefs()).toEqual(defaultOfferListPrefs());
  });
});

describe('saveOfferListPrefs', () => {
  it('round-trips exactly what was saved', () => {
    const prefs = {
      filters: { source: 'justjoinit', showApplied: true, showHidden: false },
      minScore: 75,
      sort: { orderBy: 'score_percent' as const, order: 'asc' as const },
    };

    saveOfferListPrefs(prefs);

    expect(loadOfferListPrefs()).toEqual(prefs);
  });
});
