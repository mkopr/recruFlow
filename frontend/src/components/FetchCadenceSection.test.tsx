import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as useFetchCadenceModule from '../hooks/useFetchCadence';
import { FetchCadenceSection } from './FetchCadenceSection';
import { KNOWN_SOURCES } from '../constants';

vi.mock('../hooks/useFetchCadence', () => ({
  useFetchCadence: vi.fn(),
}));

const useFetchCadenceMock = vi.mocked(useFetchCadenceModule.useFetchCadence);

function baseResult(
  overrides: Partial<useFetchCadenceModule.UseFetchCadenceResult> = {},
): useFetchCadenceModule.UseFetchCadenceResult {
  return {
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
    saving: {},
    error: null,
    saveOne: vi.fn(),
    saveAll: vi.fn(),
    refetch: vi.fn(),
    ...overrides,
  };
}

beforeEach(() => {
  useFetchCadenceMock.mockReset();
});

describe('FetchCadenceSection', () => {
  it('renders one row per connector pre-filled with its current interval in minutes', () => {
    useFetchCadenceMock.mockReturnValue(baseResult());

    render(<FetchCadenceSection />);

    for (const source of KNOWN_SOURCES) {
      expect(screen.getByText(source.label)).toBeInTheDocument();
    }
    const inputs = screen.getAllByRole('spinbutton') as HTMLInputElement[];
    // 300 seconds = 5 minutes, for every connector row
    expect(inputs.slice(0, KNOWN_SOURCES.length).every((input) => input.value === '5')).toBe(true);
  });

  it('apply-to-all control calls saveAll with the entered value', async () => {
    const saveAll = vi.fn();
    useFetchCadenceMock.mockReturnValue(baseResult({ saveAll }));

    render(<FetchCadenceSection />);

    const applyAllButton = screen.getByRole('button', { name: 'Apply to all' });
    await userEvent.click(applyAllButton);

    expect(saveAll).toHaveBeenCalledWith(300);
  });

  it('each row saves independently: a saving row disables only its own Save button', () => {
    useFetchCadenceMock.mockReturnValue(baseResult({ saving: { [KNOWN_SOURCES[0]!.id]: true } }));

    render(<FetchCadenceSection />);

    const saveButtons = screen.getAllByRole('button', { name: /Save|Saving/ });
    expect(saveButtons[0]).toBeDisabled();
    expect(saveButtons.slice(1).every((button) => !button.hasAttribute('disabled'))).toBe(true);
  });
});
