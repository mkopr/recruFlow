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
    const saveRange = vi.fn().mockResolvedValue(true);
    useFetchRangeSettingsMock.mockReturnValue(baseResult({ saveRange }));

    render(<FetchRangeSection />);

    const saveButtons = screen.getAllByRole('button', { name: /Save|Saving/ });
    await userEvent.click(saveButtons[0]!);

    expect(saveRange).toHaveBeenCalledWith(
      KNOWN_SOURCES[0]!.id,
      expect.objectContaining({ mode: 'range', since: '2026-06-01T00:00:00.000Z' }),
    );
  });

  it('after a successful since-only save, the row reflects the server-confirmed until (not the pre-save draft)', async () => {
    const sourcesWithConcreteUntil = KNOWN_SOURCES.map((known) => ({
      source_id: 1,
      connector: known.id,
      name: known.id,
      schedule: { type: 'interval' as const, seconds: 300 },
      fetch_range: { mode: 'range', since: '2026-06-01T00:00:00Z', until: '2026-06-30T00:00:00Z' },
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
    }));
    const sourcesWithConfirmedOpenEnded = sourcesWithConcreteUntil.map((source) => ({
      ...source,
      fetch_range: { ...source.fetch_range, until: null },
    }));

    // saveRange resolves true and, like the real hook, its resolution implies `refetch()`
    // already landed -- so by the time the row re-renders, `sources` carries the
    // server-confirmed value rather than the pre-save draft.
    const saveRange = vi.fn().mockImplementation(async () => {
      useFetchRangeSettingsMock.mockReturnValue(
        baseResult({ saveRange, sources: sourcesWithConfirmedOpenEnded }),
      );
      return true;
    });
    useFetchRangeSettingsMock.mockReturnValue(
      baseResult({ saveRange, sources: sourcesWithConcreteUntil }),
    );

    const { container } = render(<FetchRangeSection />);

    // First row's "until" input is the 2nd datetime-local input (since, until pair).
    const untilInput = container.querySelectorAll('input[type="datetime-local"]')[1]!;
    expect((untilInput as HTMLInputElement).value).not.toBe('');
    await userEvent.clear(untilInput);
    expect(untilInput).toHaveValue('');

    const saveButtons = screen.getAllByRole('button', { name: /Save|Saving/ });
    await userEvent.click(saveButtons[0]!);

    // The row must show the server-confirmed blank "until" -- not stuck displaying
    // whatever the local draft had at click time -- and label the resulting mode.
    const reconciledUntilInput = container.querySelectorAll('input[type="datetime-local"]')[1]!;
    expect(reconciledUntilInput).toHaveValue('');
    expect(screen.getAllByText(/Real-time \(no end date\)/).length).toBeGreaterThan(0);
  });

  it('labels the open-ended/real-time state with helper copy when "until" is blank', () => {
    useFetchRangeSettingsMock.mockReturnValue(
      baseResult({
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
      }),
    );

    render(<FetchRangeSection />);

    // One label per connector row, plus one for the "apply to all" range block (which
    // also defaults to a blank "until").
    expect(screen.getAllByText(/Real-time \(no end date\)/).length).toBe(KNOWN_SOURCES.length + 1);
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
