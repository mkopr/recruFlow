import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ConnectorOption } from '../api/connectors';
import * as useConnectorSettingsModule from '../hooks/useConnectorSettings';
import * as useKnownSourcesModule from '../hooks/useKnownSources';
import { ConnectorSettingsSection } from './ConnectorSettingsSection';

vi.mock('../hooks/useKnownSources', () => ({
  useKnownSources: vi.fn(),
}));

vi.mock('../hooks/useConnectorSettings', () => ({
  useConnectorSettings: vi.fn(),
}));

const useKnownSourcesMock = vi.mocked(useKnownSourcesModule.useKnownSources);
const useConnectorSettingsMock = vi.mocked(useConnectorSettingsModule.useConnectorSettings);

const THREE_SOURCES: ConnectorOption[] = [
  { id: 'solid_jobs', label: 'SOLID.Jobs' },
  { id: 'justjoinit', label: 'JustJoin.it' },
  { id: 'nofluffjobs', label: 'NoFluffJobs' },
];

function baseSettings(
  overrides: Partial<useConnectorSettingsModule.UseConnectorSettingsResult> = {},
): useConnectorSettingsModule.UseConnectorSettingsResult {
  return {
    sources: [],
    savingByConnector: {},
    error: null,
    saveInterval: vi.fn(),
    saveIntervalAll: vi.fn(),
    saveRange: vi.fn(),
    saveRangeAll: vi.fn(),
    saveAutoFetch: vi.fn(),
    saveAutoFetchAll: vi.fn(),
    saveEnabled: vi.fn(),
    saveEnabledAll: vi.fn(),
    refetch: vi.fn(),
    ...overrides,
  };
}

beforeEach(() => {
  useKnownSourcesMock.mockReset();
  useConnectorSettingsMock.mockReset();
});

describe('ConnectorSettingsSection', () => {
  it('renders one ConnectorSettingsCard per known source', () => {
    useKnownSourcesMock.mockReturnValue({ sources: THREE_SOURCES });
    useConnectorSettingsMock.mockReturnValue(baseSettings());

    render(<ConnectorSettingsSection />);

    for (const source of THREE_SOURCES) {
      expect(screen.getByText(source.label)).toBeInTheDocument();
    }
  });

  it('apply-to-all cadence control calls saveIntervalAll with the entered value', async () => {
    useKnownSourcesMock.mockReturnValue({ sources: THREE_SOURCES });
    const saveIntervalAll = vi.fn();
    useConnectorSettingsMock.mockReturnValue(baseSettings({ saveIntervalAll }));

    render(<ConnectorSettingsSection />);

    await userEvent.click(screen.getByRole('button', { name: 'Apply cadence' }));

    expect(saveIntervalAll).toHaveBeenCalledWith(300);
  });

  it('apply-to-all range control calls saveRangeAll with the selected value', async () => {
    useKnownSourcesMock.mockReturnValue({ sources: THREE_SOURCES });
    const saveRangeAll = vi.fn();
    useConnectorSettingsMock.mockReturnValue(baseSettings({ saveRangeAll }));

    render(<ConnectorSettingsSection />);

    await userEvent.selectOptions(screen.getAllByDisplayValue('Date range')[0]!, 'all');
    await userEvent.click(screen.getByRole('button', { name: 'Apply range' }));

    expect(saveRangeAll).toHaveBeenCalledWith({ mode: 'all' });
  });

  it('apply-to-all auto-fetch control calls saveAutoFetchAll with the selected value', async () => {
    useKnownSourcesMock.mockReturnValue({ sources: THREE_SOURCES });
    const saveAutoFetchAll = vi.fn();
    useConnectorSettingsMock.mockReturnValue(baseSettings({ saveAutoFetchAll }));

    render(<ConnectorSettingsSection />);

    const applyButtons = screen.getAllByRole('button', { name: 'Apply' });
    await userEvent.click(applyButtons[0]!);

    expect(saveAutoFetchAll).toHaveBeenCalledWith(true);
  });

  it('apply-to-all stop/start control calls saveEnabledAll with the selected value', async () => {
    useKnownSourcesMock.mockReturnValue({ sources: THREE_SOURCES });
    const saveEnabledAll = vi.fn();
    useConnectorSettingsMock.mockReturnValue(baseSettings({ saveEnabledAll }));

    render(<ConnectorSettingsSection />);

    const applyButtons = screen.getAllByRole('button', { name: 'Apply' });
    await userEvent.click(applyButtons[1]!);

    expect(saveEnabledAll).toHaveBeenCalledWith(true);
  });

  it('scales to 10 connectors (3 real + 7 made-up) with no thrown error', () => {
    const tenSources: ConnectorOption[] = [
      ...THREE_SOURCES,
      ...Array.from({ length: 7 }, (_, i) => ({ id: `made-up-${i}`, label: `Made Up ${i}` })),
    ];
    useKnownSourcesMock.mockReturnValue({ sources: tenSources });
    useConnectorSettingsMock.mockReturnValue(baseSettings());

    render(<ConnectorSettingsSection />);

    for (const source of tenSources) {
      expect(screen.getByText(source.label)).toBeInTheDocument();
    }
  });
});
