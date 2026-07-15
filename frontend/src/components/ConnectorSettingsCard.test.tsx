import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { ConnectorOption } from '../api/connectors';
import type { SourceStatus } from '../api/scheduler';
import type { UseConnectorSettingsResult } from '../hooks/useConnectorSettings';
import { ConnectorSettingsCard } from './ConnectorSettingsCard';

function makeSource(overrides: Partial<SourceStatus> = {}): SourceStatus {
  return {
    source_id: 1,
    connector: 'justjoinit',
    name: 'justjoinit',
    schedule: { type: 'interval', seconds: 300 },
    fetch_range: { mode: 'all', since: null, until: null },
    fetch_scope: { mode: 'all' },
    auto_fetch_enabled: true,
    connector_enabled: true,
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
    ...overrides,
  };
}

function makeSettings(
  overrides: Partial<UseConnectorSettingsResult> = {},
): UseConnectorSettingsResult {
  return {
    sources: [makeSource()],
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

const source: ConnectorOption = {
  id: 'justjoinit',
  label: 'JustJoin.it',
  offer_count: 0,
  scored_count: 0,
  unscored_count: 0,
  supports_fetch_scope: false,
};

describe('ConnectorSettingsCard', () => {
  it('renders the label, cadence input, auto-fetch checkbox, and stop/start control from status', () => {
    const settings = makeSettings({
      sources: [
        makeSource({
          schedule: { seconds: 600 },
          auto_fetch_enabled: false,
          connector_enabled: false,
        }),
      ],
    });

    render(<ConnectorSettingsCard source={source} settings={settings} />);

    expect(screen.getByText('JustJoin.it')).toBeInTheDocument();
    expect((screen.getAllByRole('spinbutton')[0] as HTMLInputElement).value).toBe('10');
    expect(screen.getByRole('checkbox', { name: /Auto-fetch/ })).not.toBeChecked();
    expect(screen.getByRole('checkbox', { name: /Running|Stopped/ })).not.toBeChecked();
    expect(screen.getByText('Stopped')).toBeInTheDocument();
  });

  it('clicking Save on the cadence row calls saveInterval with the entered seconds', async () => {
    const saveInterval = vi.fn();
    const settings = makeSettings({ saveInterval });

    render(<ConnectorSettingsCard source={source} settings={settings} />);

    await userEvent.click(screen.getAllByRole('button', { name: /Save/ })[0]!);

    expect(saveInterval).toHaveBeenCalledWith('justjoinit', 300);
  });

  it('clicking the stop/start control calls saveEnabled with the flipped value', async () => {
    const saveEnabled = vi.fn();
    const settings = makeSettings({
      sources: [makeSource({ connector_enabled: true })],
      saveEnabled,
    });

    render(<ConnectorSettingsCard source={source} settings={settings} />);

    await userEvent.click(screen.getByRole('checkbox', { name: /Running|Stopped/ }));

    expect(saveEnabled).toHaveBeenCalledWith('justjoinit', false);
  });

  it('each card saves independently: a saving card disables only its own Save buttons', () => {
    const settingsA = makeSettings({
      sources: [makeSource({ connector: 'justjoinit' })],
      savingByConnector: { justjoinit: true },
    });
    const settingsB = makeSettings({
      sources: [makeSource({ connector: 'nofluffjobs' })],
      savingByConnector: { justjoinit: true },
    });

    render(
      <>
        <ConnectorSettingsCard
          source={{
            id: 'justjoinit',
            label: 'JustJoin.it',
            offer_count: 0,
            scored_count: 0,
            unscored_count: 0,
            supports_fetch_scope: false,
          }}
          settings={settingsA}
        />
        <ConnectorSettingsCard
          source={{
            id: 'nofluffjobs',
            label: 'NoFluffJobs',
            offer_count: 0,
            scored_count: 0,
            unscored_count: 0,
            supports_fetch_scope: false,
          }}
          settings={settingsB}
        />
      </>,
    );

    const saveButtons = screen.getAllByRole('button', { name: /Save|Saving/ });
    expect(saveButtons[0]).toBeDisabled();
    expect(saveButtons[1]).toBeDisabled();
    expect(saveButtons[2]).not.toBeDisabled();
    expect(saveButtons[3]).not.toBeDisabled();
  });

  it('renders the Fetch scope control only when supports_fetch_scope is true', () => {
    const settings = makeSettings();

    render(
      <ConnectorSettingsCard
        source={{ ...source, supports_fetch_scope: true }}
        settings={settings}
      />,
    );

    expect(screen.getByText('Fetch scope')).toBeInTheDocument();
  });

  it('does not render the Fetch scope control when supports_fetch_scope is false', () => {
    const settings = makeSettings();

    render(<ConnectorSettingsCard source={source} settings={settings} />);

    expect(screen.queryByText('Fetch scope')).not.toBeInTheDocument();
  });

  it('clicking Save on the fetch scope row calls saveFetchScope with the selected mode', async () => {
    const saveFetchScope = vi.fn();
    const settings = makeSettings({ saveFetchScope });

    render(
      <ConnectorSettingsCard
        source={{ ...source, supports_fetch_scope: true }}
        settings={settings}
      />,
    );

    await userEvent.selectOptions(screen.getByDisplayValue('All offers'), 'filtered');
    const saveButtons = screen.getAllByRole('button', { name: /Save/ });
    await userEvent.click(saveButtons[saveButtons.length - 1]!);

    expect(saveFetchScope).toHaveBeenCalledWith('justjoinit', 'filtered');
  });
});
