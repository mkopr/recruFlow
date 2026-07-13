import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as useFetchCadenceModule from '../hooks/useFetchCadence';
import * as useFetchRangeSettingsModule from '../hooks/useFetchRangeSettings';
import { SettingsPage } from './SettingsPage';

vi.mock('../hooks/useFetchCadence', () => ({
  useFetchCadence: vi.fn(),
}));

vi.mock('../hooks/useFetchRangeSettings', () => ({
  useFetchRangeSettings: vi.fn(),
}));

const useFetchCadenceMock = vi.mocked(useFetchCadenceModule.useFetchCadence);
const useFetchRangeSettingsMock = vi.mocked(useFetchRangeSettingsModule.useFetchRangeSettings);

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

  useFetchRangeSettingsMock.mockReset();
  useFetchRangeSettingsMock.mockReturnValue({
    sources: [],
    savingByConnector: {},
    error: null,
    saveRange: vi.fn(),
    saveRangeAll: vi.fn(),
    saveAutoFetch: vi.fn(),
    saveAutoFetchAll: vi.fn(),
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

  it('renders the fetch cadence, fetch range, offer cleanup, and notifications sections', () => {
    render(<SettingsPage />);

    expect(screen.getByText(/Fetch cadence:/)).toBeInTheDocument();
    expect(screen.getByText(/Fetch range & auto-fetch:/)).toBeInTheDocument();
    expect(screen.getByText(/Offer cleanup:/)).toBeInTheDocument();
    expect(screen.getByText(/Notifications:/)).toBeInTheDocument();
    expect(screen.getByLabelText('Minimum score for alert (%)')).toBeInTheDocument();
  });

  it('places the offer cleanup section between fetch range and notifications', () => {
    const { container } = render(<SettingsPage />);

    const text = container.textContent ?? '';
    const fetchRangeIndex = text.indexOf('Fetch range & auto-fetch:');
    const cleanupIndex = text.indexOf('Offer cleanup:');
    const notificationsIndex = text.indexOf('Notifications:');

    expect(fetchRangeIndex).toBeGreaterThanOrEqual(0);
    expect(cleanupIndex).toBeGreaterThan(fetchRangeIndex);
    expect(notificationsIndex).toBeGreaterThan(cleanupIndex);
  });
});
