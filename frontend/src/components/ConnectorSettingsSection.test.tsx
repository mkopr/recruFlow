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
  {
    id: 'solid_jobs',
    label: 'SOLID.Jobs',
    offer_count: 0,
    scored_count: 0,
    unscored_count: 0,
    supports_fetch_scope: false,
  },
  {
    id: 'justjoinit',
    label: 'JustJoin.it',
    offer_count: 0,
    scored_count: 0,
    unscored_count: 0,
    supports_fetch_scope: false,
  },
  {
    id: 'nofluffjobs',
    label: 'NoFluffJobs',
    offer_count: 0,
    scored_count: 0,
    unscored_count: 0,
    supports_fetch_scope: false,
  },
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
    saveFetchScope: vi.fn(),
    saveAutoFetch: vi.fn(),
    saveAutoFetchAll: vi.fn(),
    saveEnabled: vi.fn(),
    saveEnabledAll: vi.fn(),
    refetch: vi.fn(),
    ...overrides,
  };
}

beforeEach(() => {
  localStorage.clear();
  useKnownSourcesMock.mockReset();
  useConnectorSettingsMock.mockReset();
});

describe('ConnectorSettingsSection', () => {
  it("renders a tab per known source, with only the first connector's card visible by default", () => {
    useKnownSourcesMock.mockReturnValue({ sources: THREE_SOURCES, refetch: vi.fn() });
    useConnectorSettingsMock.mockReturnValue(baseSettings());

    render(<ConnectorSettingsSection />);

    const tabs = screen.getAllByRole('tab');
    expect(tabs).toHaveLength(3);
    expect(tabs.map((tab) => tab.textContent)).toEqual([
      'SOLID.Jobs',
      'JustJoin.it',
      'NoFluffJobs',
    ]);

    // The first connector's card is visible: its label appears in both the tab and the card.
    expect(screen.getAllByText('SOLID.Jobs')).toHaveLength(2);
    // The other connectors only appear as tab labels, not duplicated in card content.
    expect(screen.getAllByText('JustJoin.it')).toHaveLength(1);
    expect(screen.getAllByText('NoFluffJobs')).toHaveLength(1);
  });

  it('clicking a different tab switches the visible ConnectorSettingsCard', async () => {
    useKnownSourcesMock.mockReturnValue({ sources: THREE_SOURCES, refetch: vi.fn() });
    useConnectorSettingsMock.mockReturnValue(baseSettings());

    render(<ConnectorSettingsSection />);

    expect(screen.getAllByText('SOLID.Jobs')).toHaveLength(2);
    expect(screen.getAllByText('JustJoin.it')).toHaveLength(1);

    await userEvent.click(screen.getByRole('tab', { name: 'JustJoin.it' }));

    expect(screen.getAllByText('SOLID.Jobs')).toHaveLength(1);
    expect(screen.getAllByText('JustJoin.it')).toHaveLength(2);
  });

  it('apply-to-all cadence control calls saveIntervalAll with the entered value', async () => {
    useKnownSourcesMock.mockReturnValue({ sources: THREE_SOURCES, refetch: vi.fn() });
    const saveIntervalAll = vi.fn();
    useConnectorSettingsMock.mockReturnValue(baseSettings({ saveIntervalAll }));

    render(<ConnectorSettingsSection />);

    await userEvent.click(screen.getByRole('button', { name: 'Apply cadence' }));

    expect(saveIntervalAll).toHaveBeenCalledWith(300);
  });

  it('apply-to-all range control calls saveRangeAll with the selected value', async () => {
    useKnownSourcesMock.mockReturnValue({ sources: THREE_SOURCES, refetch: vi.fn() });
    const saveRangeAll = vi.fn();
    useConnectorSettingsMock.mockReturnValue(baseSettings({ saveRangeAll }));

    render(<ConnectorSettingsSection />);

    await userEvent.selectOptions(screen.getAllByDisplayValue('Date range')[0]!, 'all');
    await userEvent.click(screen.getByRole('button', { name: 'Apply range' }));

    expect(saveRangeAll).toHaveBeenCalledWith({ mode: 'all' });
  });

  it('apply-to-all auto-fetch control calls saveAutoFetchAll with the selected value', async () => {
    useKnownSourcesMock.mockReturnValue({ sources: THREE_SOURCES, refetch: vi.fn() });
    const saveAutoFetchAll = vi.fn();
    useConnectorSettingsMock.mockReturnValue(baseSettings({ saveAutoFetchAll }));

    render(<ConnectorSettingsSection />);

    const applyButtons = screen.getAllByRole('button', { name: 'Apply' });
    await userEvent.click(applyButtons[0]!);

    expect(saveAutoFetchAll).toHaveBeenCalledWith(true);
  });

  it('apply-to-all stop/start control calls saveEnabledAll with the selected value, even after switching tabs', async () => {
    useKnownSourcesMock.mockReturnValue({ sources: THREE_SOURCES, refetch: vi.fn() });
    const saveEnabledAll = vi.fn();
    useConnectorSettingsMock.mockReturnValue(baseSettings({ saveEnabledAll }));

    render(<ConnectorSettingsSection />);

    await userEvent.click(screen.getByRole('tab', { name: 'NoFluffJobs' }));

    const applyButtons = screen.getAllByRole('button', { name: 'Apply' });
    await userEvent.click(applyButtons[1]!);

    expect(saveEnabledAll).toHaveBeenCalledWith(true);
  });

  it('scales to 10 connectors (3 real + 7 made-up) with no thrown error, showing exactly one card at a time', () => {
    const tenSources: ConnectorOption[] = [
      ...THREE_SOURCES,
      ...Array.from({ length: 7 }, (_, i) => ({
        id: `made-up-${i}`,
        label: `Made Up ${i}`,
        offer_count: 0,
        scored_count: 0,
        unscored_count: 0,
        supports_fetch_scope: false,
      })),
    ];
    useKnownSourcesMock.mockReturnValue({ sources: tenSources, refetch: vi.fn() });
    useConnectorSettingsMock.mockReturnValue(baseSettings());

    render(<ConnectorSettingsSection />);

    expect(screen.getAllByRole('tab')).toHaveLength(10);
    expect(screen.getAllByText('SOLID.Jobs')).toHaveLength(2);
  });

  it('persists the selected tab across remounts', async () => {
    useKnownSourcesMock.mockReturnValue({ sources: THREE_SOURCES, refetch: vi.fn() });
    useConnectorSettingsMock.mockReturnValue(baseSettings());

    const { unmount } = render(<ConnectorSettingsSection />);
    await userEvent.click(screen.getByRole('tab', { name: 'NoFluffJobs' }));
    expect(screen.getByRole('tab', { name: 'NoFluffJobs' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    unmount();

    render(<ConnectorSettingsSection />);

    expect(screen.getByRole('tab', { name: 'NoFluffJobs' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(screen.getByRole('tab', { name: 'SOLID.Jobs' })).toHaveAttribute(
      'aria-selected',
      'false',
    );
  });

  it('falls back to the first connector when the persisted tab id no longer exists in the registry', () => {
    localStorage.setItem('recruflow.connectorSettingsTab', 'a-connector-id-not-in-THREE_SOURCES');
    useKnownSourcesMock.mockReturnValue({ sources: THREE_SOURCES, refetch: vi.fn() });
    useConnectorSettingsMock.mockReturnValue(baseSettings());

    render(<ConnectorSettingsSection />);

    expect(screen.getByRole('tab', { name: 'SOLID.Jobs' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
  });

  it('tab strip is driven entirely by the registry, with zero hardcoded connector ids', () => {
    useKnownSourcesMock.mockReturnValue({
      sources: [
        {
          id: 'zzz-fixture-only',
          label: 'Zzz Fixture Only',
          offer_count: 0,
          scored_count: 0,
          unscored_count: 0,
          supports_fetch_scope: false,
        },
      ],
      refetch: vi.fn(),
    });
    useConnectorSettingsMock.mockReturnValue(baseSettings());

    render(<ConnectorSettingsSection />);

    expect(screen.getByRole('tab', { name: 'Zzz Fixture Only' })).toBeInTheDocument();
  });
});
