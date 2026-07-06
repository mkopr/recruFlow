import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as useScoringConfigModule from '../hooks/useScoringConfig';
import { SettingsPage } from './SettingsPage';

vi.mock('../hooks/useScoringConfig', () => ({
  useScoringConfig: vi.fn(),
}));

const useScoringConfigMock = vi.mocked(useScoringConfigModule.useScoringConfig);

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
    await userEvent.click(screen.getByText('Save'));

    expect(save).toHaveBeenCalledTimes(1);
  });

  it('disables the Save button while settings.saving is true', () => {
    useScoringConfigMock.mockReturnValue(baseResult({ saving: true }));

    render(<SettingsPage />);

    expect(screen.getByText('Save')).toBeDisabled();
  });
});
