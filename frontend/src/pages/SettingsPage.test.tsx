import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as useConnectorSettingsModule from '../hooks/useConnectorSettings';
import * as useKnownSourcesModule from '../hooks/useKnownSources';
import { SettingsPage } from './SettingsPage';

vi.mock('../hooks/useKnownSources', () => ({
  useKnownSources: vi.fn(),
}));

vi.mock('../hooks/useConnectorSettings', () => ({
  useConnectorSettings: vi.fn(),
}));

const useKnownSourcesMock = vi.mocked(useKnownSourcesModule.useKnownSources);
const useConnectorSettingsMock = vi.mocked(useConnectorSettingsModule.useConnectorSettings);

beforeEach(() => {
  useKnownSourcesMock.mockReset();
  useKnownSourcesMock.mockReturnValue({ sources: [], refetch: vi.fn() });

  useConnectorSettingsMock.mockReset();
  useConnectorSettingsMock.mockReturnValue({
    sources: [],
    savingByConnector: {},
    error: null,
    saveInterval: vi.fn(),
    saveIntervalAll: vi.fn(),
    saveRange: vi.fn(),
    saveRangeAll: vi.fn(),
    saveFetchScope: vi.fn(),
    saveAutoFetch: vi.fn(),
    saveAutoFetchAll: vi.fn(),
    saveEnabled: vi.fn(),
    saveEnabledAll: vi.fn(),
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

  it('renders the connectors, offer cleanup, and notifications sections', () => {
    render(<SettingsPage />);

    expect(screen.getByText(/Connectors:/)).toBeInTheDocument();
    expect(screen.getByText(/Offer cleanup:/)).toBeInTheDocument();
    expect(screen.getByText(/Notifications:/)).toBeInTheDocument();
    expect(screen.getByLabelText('Minimum score for alert (%)')).toBeInTheDocument();
  });

  it('places the offer cleanup section between connectors and notifications', () => {
    const { container } = render(<SettingsPage />);

    const text = container.textContent ?? '';
    const connectorsIndex = text.indexOf('Connectors:');
    const cleanupIndex = text.indexOf('Offer cleanup:');
    const notificationsIndex = text.indexOf('Notifications:');

    expect(connectorsIndex).toBeGreaterThanOrEqual(0);
    expect(cleanupIndex).toBeGreaterThan(connectorsIndex);
    expect(notificationsIndex).toBeGreaterThan(cleanupIndex);
  });
});
