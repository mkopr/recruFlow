import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { KNOWN_SOURCES } from '../constants';
import * as useFetchRangeSettingsModule from '../hooks/useFetchRangeSettings';
import { FetchRangeSection } from './FetchRangeSection';

vi.mock('../hooks/useFetchRangeSettings', () => ({
  useFetchRangeSettings: vi.fn(),
}));

const useFetchRangeSettingsMock = vi.mocked(useFetchRangeSettingsModule.useFetchRangeSettings);

function baseResult(
  overrides: Partial<useFetchRangeSettingsModule.UseFetchRangeSettingsResult> = {},
): useFetchRangeSettingsModule.UseFetchRangeSettingsResult {
  return {
    sources: KNOWN_SOURCES.map((source) => ({
      source_id: 1,
      connector: source.id,
      name: source.id,
      schedule: { type: 'interval', seconds: 300 },
      fetch_range: { mode: 'range', since: '2026-06-01T00:00:00Z', until: null },
      auto_fetch_enabled: true,
      last_fetched_at: null,
      last_run_id: null,
      last_run_started_at: null,
      last_run_finished_at: null,
      last_run_status: null,
      last_run_trigger_type: null,
      last_run_fetched: null,
      last_run_created: null,
      last_run_warning: false,
      last_run_error_message: null,
    })),
    savingByConnector: {},
    error: null,
    saveRange: vi.fn(),
    saveRangeAll: vi.fn(),
    saveAutoFetch: vi.fn(),
    saveAutoFetchAll: vi.fn(),
    refetch: vi.fn(),
    ...overrides,
  };
}

beforeEach(() => {
  useFetchRangeSettingsMock.mockReset();
});

describe('FetchRangeSection', () => {
  it('renders one row per connector pre-filled with its auto-fetch state and mode', () => {
    useFetchRangeSettingsMock.mockReturnValue(baseResult());

    render(<FetchRangeSection />);

    for (const source of KNOWN_SOURCES) {
      expect(screen.getByText(source.label)).toBeInTheDocument();
    }
    const checkboxes = screen.getAllByRole('checkbox') as HTMLInputElement[];
    expect(checkboxes.every((checkbox) => checkbox.checked)).toBe(true);
  });

  it('since/until datetime inputs are only present when mode is "range"', () => {
    useFetchRangeSettingsMock.mockReturnValue(
      baseResult({
        sources: KNOWN_SOURCES.map((source) => ({
          source_id: 1,
          connector: source.id,
          name: source.id,
          schedule: { type: 'interval', seconds: 300 },
          fetch_range: { mode: 'all', since: null, until: null },
          auto_fetch_enabled: true,
          last_fetched_at: null,
          last_run_id: null,
          last_run_started_at: null,
          last_run_finished_at: null,
          last_run_status: null,
          last_run_trigger_type: null,
          last_run_fetched: null,
          last_run_created: null,
          last_run_warning: false,
          last_run_error_message: null,
        })),
      }),
    );

    const { container } = render(<FetchRangeSection />);

    // Every connector row is in "all" mode -- the only datetime inputs left are the
    // apply-to-all range block's own (independent) since/until pair.
    expect(container.querySelectorAll('input[type="datetime-local"]')).toHaveLength(2);
  });

  it('renders since/until datetime inputs when mode is "range"', () => {
    useFetchRangeSettingsMock.mockReturnValue(baseResult());

    const { container } = render(<FetchRangeSection />);

    // One connector row (range mode) x 2 date inputs, plus the apply-to-all range block
    // (also defaulted to range mode) x 2 date inputs.
    expect(
      container.querySelectorAll('input[type="datetime-local"]').length,
    ).toBeGreaterThanOrEqual(KNOWN_SOURCES.length * 2);
  });

  it("clicking a row's Save button calls saveRange with the row's current fetch_range", async () => {
    const saveRange = vi.fn();
    useFetchRangeSettingsMock.mockReturnValue(baseResult({ saveRange }));

    render(<FetchRangeSection />);

    const saveButtons = screen.getAllByRole('button', { name: /Save|Saving/ });
    await userEvent.click(saveButtons[0]!);

    expect(saveRange).toHaveBeenCalledWith(
      KNOWN_SOURCES[0]!.id,
      expect.objectContaining({ mode: 'range', since: '2026-06-01T00:00:00.000Z' }),
    );
  });

  it('toggling the auto-fetch checkbox calls saveAutoFetch with the connector and new value', async () => {
    const saveAutoFetch = vi.fn();
    useFetchRangeSettingsMock.mockReturnValue(baseResult({ saveAutoFetch }));

    render(<FetchRangeSection />);

    const checkboxes = screen.getAllByRole('checkbox');
    await userEvent.click(checkboxes[0]!);

    expect(saveAutoFetch).toHaveBeenCalledWith(KNOWN_SOURCES[0]!.id, false);
  });

  it('apply-to-all range control calls saveRangeAll', async () => {
    const saveRangeAll = vi.fn();
    useFetchRangeSettingsMock.mockReturnValue(baseResult({ saveRangeAll }));

    render(<FetchRangeSection />);

    const applyButtons = screen.getAllByRole('button', { name: 'Apply to all' });
    await userEvent.click(applyButtons[0]!);

    expect(saveRangeAll).toHaveBeenCalledWith(expect.objectContaining({ mode: 'range' }));
  });

  it('apply-to-all auto-fetch control calls saveAutoFetchAll', async () => {
    const saveAutoFetchAll = vi.fn();
    useFetchRangeSettingsMock.mockReturnValue(baseResult({ saveAutoFetchAll }));

    render(<FetchRangeSection />);

    const applyButtons = screen.getAllByRole('button', { name: 'Apply to all' });
    await userEvent.click(applyButtons[1]!);

    expect(saveAutoFetchAll).toHaveBeenCalledWith(true);
  });

  it('each row saves independently: a saving row disables only its own Save button', () => {
    useFetchRangeSettingsMock.mockReturnValue(
      baseResult({ savingByConnector: { [KNOWN_SOURCES[0]!.id]: true } }),
    );

    render(<FetchRangeSection />);

    const saveButtons = screen.getAllByRole('button', { name: /Save|Saving/ });
    expect(saveButtons[0]).toBeDisabled();
    expect(saveButtons.slice(1).every((button) => !button.hasAttribute('disabled'))).toBe(true);
  });
});
