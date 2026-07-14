import { beforeEach, describe, expect, it } from 'vitest';

import { loadSelectedConnectorTab, saveSelectedConnectorTab } from './connectorSettingsTabPrefs';

beforeEach(() => {
  localStorage.clear();
});

describe('connectorSettingsTabPrefs', () => {
  it('loadSelectedConnectorTab returns null when nothing is stored', () => {
    expect(loadSelectedConnectorTab()).toBeNull();
  });

  it('saveSelectedConnectorTab then loadSelectedConnectorTab round-trips the exact id that was saved', () => {
    saveSelectedConnectorTab('justjoinit');

    expect(loadSelectedConnectorTab()).toBe('justjoinit');
  });

  it('a second save overwrites the first, and load reflects only the latest value', () => {
    saveSelectedConnectorTab('justjoinit');
    saveSelectedConnectorTab('solid_jobs');

    expect(loadSelectedConnectorTab()).toBe('solid_jobs');
  });
});
