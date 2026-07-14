import { useEffect, useState } from 'react';

import type { ConnectorOption } from '../api/connectors';
import { useConnectorSettings } from '../hooks/useConnectorSettings';
import { useKnownSources } from '../hooks/useKnownSources';
import { buildRequest, type RangeDraft } from '../lib/connectorSettingsDraft';
import {
  loadSelectedConnectorTab,
  saveSelectedConnectorTab,
} from '../lib/connectorSettingsTabPrefs';
import { ConnectorSettingsCard } from './ConnectorSettingsCard';

// A persisted tab id may point at a connector that no longer exists (removed
// from the registry) or nothing may be selected yet -- fall back to the
// registry's first entry rather than rendering no tab as active.
function resolveActiveTabId(
  knownSources: ConnectorOption[],
  selectedTab: string | null,
): string | null {
  if (selectedTab !== null && knownSources.some((source) => source.id === selectedTab)) {
    return selectedTab;
  }
  return knownSources[0]?.id ?? null;
}

export function ConnectorSettingsSection() {
  const { sources: knownSources } = useKnownSources();
  const settings = useConnectorSettings();

  const [applyAllMinutes, setApplyAllMinutes] = useState(5);
  const [applyAllDraft, setApplyAllDraft] = useState<RangeDraft>({
    mode: 'range',
    since: '',
    until: '',
  });
  const [applyAllAutoFetch, setApplyAllAutoFetch] = useState(true);
  const [applyAllEnabled, setApplyAllEnabled] = useState(true);

  const [selectedTab, setSelectedTab] = useState<string | null>(loadSelectedConnectorTab);

  useEffect(() => {
    if (selectedTab !== null) {
      saveSelectedConnectorTab(selectedTab);
    }
  }, [selectedTab]);

  const activeTabId = resolveActiveTabId(knownSources, selectedTab);
  const activeSource = knownSources.find((source) => source.id === activeTabId) ?? null;

  return (
    <div className="flex flex-col gap-4">
      {settings.error && <div className="text-sm text-[var(--color-danger)]">{settings.error}</div>}

      <div className="card flex flex-wrap items-center gap-4 p-4">
        <span className="w-full text-sm font-semibold sm:w-auto">Apply to all</span>

        <div className="flex items-center gap-2">
          <input
            type="number"
            min="1"
            step="1"
            className="input w-20"
            value={applyAllMinutes}
            onChange={(e) => setApplyAllMinutes(Number(e.target.value))}
          />
          <span className="text-xs text-[var(--color-text-muted)]">min</span>
          <button
            type="button"
            className="btn"
            onClick={() => settings.saveIntervalAll(Math.round(applyAllMinutes * 60))}
          >
            Apply cadence
          </button>
        </div>

        <div className="flex items-center gap-2">
          <select
            className="input w-28"
            value={applyAllDraft.mode}
            onChange={(e) =>
              setApplyAllDraft((prev) => ({ ...prev, mode: e.target.value as 'range' | 'all' }))
            }
          >
            <option value="range">Date range</option>
            <option value="all">Fetch all</option>
          </select>
          {applyAllDraft.mode === 'range' && (
            <>
              <input
                type="datetime-local"
                className="input"
                value={applyAllDraft.since}
                onChange={(e) => setApplyAllDraft((prev) => ({ ...prev, since: e.target.value }))}
              />
              <input
                type="datetime-local"
                className="input"
                value={applyAllDraft.until}
                onChange={(e) => setApplyAllDraft((prev) => ({ ...prev, until: e.target.value }))}
              />
            </>
          )}
          <button
            type="button"
            className="btn"
            onClick={() => settings.saveRangeAll(buildRequest(applyAllDraft))}
          >
            Apply range
          </button>
        </div>

        <div className="flex items-center gap-2">
          <select
            className="input w-24"
            value={applyAllAutoFetch ? 'on' : 'off'}
            onChange={(e) => setApplyAllAutoFetch(e.target.value === 'on')}
          >
            <option value="on">Auto-fetch on</option>
            <option value="off">Auto-fetch off</option>
          </select>
          <button
            type="button"
            className="btn"
            onClick={() => settings.saveAutoFetchAll(applyAllAutoFetch)}
          >
            Apply
          </button>
        </div>

        <div className="flex items-center gap-2">
          <select
            className="input w-24"
            value={applyAllEnabled ? 'on' : 'off'}
            onChange={(e) => setApplyAllEnabled(e.target.value === 'on')}
          >
            <option value="on">Start</option>
            <option value="off">Stop</option>
          </select>
          <button
            type="button"
            className="btn"
            onClick={() => settings.saveEnabledAll(applyAllEnabled)}
          >
            Apply
          </button>
        </div>
      </div>

      <div
        role="tablist"
        className="flex flex-wrap gap-2 border-b border-[var(--color-border)] pb-2"
      >
        {knownSources.map((source) => (
          <button
            key={source.id}
            type="button"
            role="tab"
            aria-selected={source.id === activeTabId}
            className={source.id === activeTabId ? 'btn btn-accent' : 'btn'}
            onClick={() => setSelectedTab(source.id)}
          >
            {source.label}
          </button>
        ))}
      </div>

      {activeSource !== null && (
        <ConnectorSettingsCard key={activeSource.id} source={activeSource} settings={settings} />
      )}
    </div>
  );
}
