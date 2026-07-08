import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as useFetchCadenceModule from '../hooks/useFetchCadence';
import { SettingsPage } from './SettingsPage';

vi.mock('../hooks/useFetchCadence', () => ({
  useFetchCadence: vi.fn(),
}));

const useFetchCadenceMock = vi.mocked(useFetchCadenceModule.useFetchCadence);

beforeEach(() => {
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
  it('renders no grade-cutoff inputs', () => {
    render(<SettingsPage />);

    expect(screen.queryByLabelText(/Grade A cutoff/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Grade B cutoff/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Grade C cutoff/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Grade D cutoff/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Save scoring config' })).not.toBeInTheDocument();
  });

  it('renders the fetch cadence and notifications sections', () => {
    render(<SettingsPage />);

    expect(screen.getByText(/Fetch cadence:/)).toBeInTheDocument();
    expect(screen.getByText(/Notifications:/)).toBeInTheDocument();
    expect(screen.getByLabelText('Minimum score for alert (%)')).toBeInTheDocument();
  });
});
