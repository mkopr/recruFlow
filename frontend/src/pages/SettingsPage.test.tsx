import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as useFetchCadenceModule from '../hooks/useFetchCadence';
import * as useScoringConfigModule from '../hooks/useScoringConfig';
import { SettingsPage } from './SettingsPage';

vi.mock('../hooks/useScoringConfig', () => ({
  useScoringConfig: vi.fn(),
}));

// FetchCadenceSection and NotificationsSection are exercised by their own test
// files; stubbing useFetchCadence here keeps this file's pre-existing
// scoring-config assertions (in particular "Save") unambiguous, since each
// cadence row also renders its own "Save" button.
vi.mock('../hooks/useFetchCadence', () => ({
  useFetchCadence: vi.fn(),
}));

const useScoringConfigMock = vi.mocked(useScoringConfigModule.useScoringConfig);
const useFetchCadenceMock = vi.mocked(useFetchCadenceModule.useFetchCadence);

function baseResult(
  overrides: Partial<useScoringConfigModule.UseScoringConfigResult> = {},
): useScoringConfigModule.UseScoringConfigResult {
  return {
    config: { grade_a: 0.85, grade_b: 0.7, grade_c: 0.55, grade_d: 0.4 },
    loading: false,
    saving: false,
    error: null,
    attemptedSubmit: false,
    validationErrors: { gradeA: false, gradeB: false, gradeC: false, gradeD: false },
    setConfig: vi.fn(),
    save: vi.fn(),
    ...overrides,
  };
}

beforeEach(() => {
  useScoringConfigMock.mockReset();
  useFetchCadenceMock.mockReset();
  useFetchCadenceMock.mockReturnValue({
    sources: [],
    saving: {},
    error: null,
    saveOne: vi.fn(),
    saveAll: vi.fn(),
    refetch: vi.fn(),
  });
});

describe('SettingsPage', () => {
  it('renders four inputs pre-filled with the hook current config values', () => {
    useScoringConfigMock.mockReturnValue(baseResult());

    render(<SettingsPage />);

    expect(screen.getByLabelText(/Grade A cutoff/)).toHaveValue(0.85);
    expect(screen.getByLabelText(/Grade B cutoff/)).toHaveValue(0.7);
    expect(screen.getByLabelText(/Grade C cutoff/)).toHaveValue(0.55);
    expect(screen.getByLabelText(/Grade D cutoff/)).toHaveValue(0.4);
  });

  it('shows an inline error message once attemptedSubmit is true and validationErrors flags it', () => {
    useScoringConfigMock.mockReturnValue(
      baseResult({
        attemptedSubmit: true,
        validationErrors: { gradeA: false, gradeB: true, gradeC: false, gradeD: false },
      }),
    );

    render(<SettingsPage />);

    expect(
      screen.getAllByText(/Must be within \(0, 1\] and strictly less than the grade above it\./),
    ).toHaveLength(1);
  });

  it('calls settings.save() when the Save button is clicked', async () => {
    const save = vi.fn();
    useScoringConfigMock.mockReturnValue(baseResult({ save }));

    render(<SettingsPage />);
    await userEvent.click(screen.getByRole('button', { name: 'Save scoring config' }));

    expect(save).toHaveBeenCalledTimes(1);
  });

  it('disables the Save button while settings.saving is true', () => {
    useScoringConfigMock.mockReturnValue(baseResult({ saving: true }));

    render(<SettingsPage />);

    expect(screen.getByRole('button', { name: 'Save scoring config' })).toBeDisabled();
  });
});
