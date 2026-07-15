import { useState } from 'react';

import type { ConnectorOption } from '../api/connectors';
import type { UseConnectorSettingsResult } from '../hooks/useConnectorSettings';
import {
  buildRequest,
  draftFromFetchRange,
  secondsToMinutes,
  type RangeDraft,
} from '../lib/connectorSettingsDraft';

interface ConnectorSettingsCardProps {
  source: ConnectorOption;
  settings: UseConnectorSettingsResult;
}

interface RangeInputsProps {
  draft: RangeDraft;
  setDraft: (updater: (prev: RangeDraft) => RangeDraft) => void;
}

function RangeInputs({ draft, setDraft }: RangeInputsProps) {
  if (draft.mode !== 'range') return null;

  return (
    <>
      <input
        type="datetime-local"
        className="input"
        value={draft.since}
        onChange={(e) => setDraft((prev) => ({ ...prev, since: e.target.value }))}
      />
      <span className="text-xs text-[var(--color-text-muted)]">until</span>
      <input
        type="datetime-local"
        className="input"
        value={draft.until}
        onChange={(e) => setDraft((prev) => ({ ...prev, until: e.target.value }))}
      />
      {draft.until === '' && (
        <span className="text-xs text-[var(--color-text-muted)]">
          Real-time (no end date) — keeps fetching the freshest postings, no cutoff
        </span>
      )}
    </>
  );
}

function resolveFetchScopeMode(
  fetchScope: Record<string, unknown> | undefined,
): 'all' | 'filtered' {
  return fetchScope?.mode === 'filtered' ? 'filtered' : 'all';
}

interface FetchScopeRowProps {
  source: ConnectorOption;
  isSaving: boolean;
  saveFetchScope: UseConnectorSettingsResult['saveFetchScope'];
  initialMode: 'all' | 'filtered';
}

function FetchScopeRow({ source, isSaving, saveFetchScope, initialMode }: FetchScopeRowProps) {
  const [fetchScopeMode, setFetchScopeMode] = useState<'all' | 'filtered'>(initialMode);

  if (!source.supports_fetch_scope) return null;

  return (
    <div className="flex flex-wrap items-center gap-3 border-t border-[var(--color-border)] pt-3">
      <span className="w-24 text-sm font-medium">Fetch scope</span>
      <select
        className="input w-48"
        value={fetchScopeMode}
        onChange={(e) => setFetchScopeMode(e.target.value as 'all' | 'filtered')}
      >
        <option value="all">All offers</option>
        <option value="filtered">Filtered by hard skills</option>
      </select>
      <button
        type="button"
        className="btn"
        disabled={isSaving}
        onClick={() => saveFetchScope(source.id, fetchScopeMode)}
      >
        {isSaving ? 'Saving…' : 'Save'}
      </button>
    </div>
  );
}

export function ConnectorSettingsCard({ source, settings }: ConnectorSettingsCardProps) {
  const status = settings.sources.find((s) => s.connector === source.id);
  const isSaving = settings.savingByConnector[source.id] ?? false;

  const [minutes, setMinutes] = useState(() => secondsToMinutes(status?.schedule?.seconds));
  const [draft, setDraft] = useState<RangeDraft>(() => draftFromFetchRange(status?.fetch_range));

  const connectorEnabled = status?.connector_enabled ?? true;
  const autoFetchEnabled = status?.auto_fetch_enabled ?? true;

  return (
    <div className="card flex flex-col gap-3 p-4">
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm font-semibold">{source.label}</span>
        <label className="flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={connectorEnabled}
            onChange={() => settings.saveEnabled(source.id, !connectorEnabled)}
          />
          {connectorEnabled ? 'Running' : 'Stopped'}
        </label>
      </div>

      <div className="flex items-center gap-3">
        <span className="w-24 text-sm font-medium">Cadence</span>
        <input
          type="number"
          min="1"
          step="1"
          className="input w-24"
          value={minutes}
          onChange={(e) => setMinutes(Number(e.target.value))}
        />
        <span className="text-xs text-[var(--color-text-muted)]">minutes</span>
        <button
          type="button"
          className="btn"
          disabled={isSaving}
          onClick={() => settings.saveInterval(source.id, Math.round(minutes * 60))}
        >
          {isSaving ? 'Saving…' : 'Save'}
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-3 border-t border-[var(--color-border)] pt-3">
        <span className="w-24 text-sm font-medium">Fetch range</span>
        <label className="flex items-center gap-1 text-xs">
          <input
            type="checkbox"
            checked={autoFetchEnabled}
            onChange={(e) => settings.saveAutoFetch(source.id, e.target.checked)}
          />
          Auto-fetch
        </label>
        <select
          className="input w-32"
          value={draft.mode}
          onChange={(e) =>
            setDraft((prev) => ({ ...prev, mode: e.target.value as 'range' | 'all' }))
          }
        >
          <option value="range">Date range</option>
          <option value="all">Fetch all</option>
        </select>
        <RangeInputs draft={draft} setDraft={setDraft} />
        <button
          type="button"
          className="btn"
          disabled={isSaving}
          onClick={() => settings.saveRange(source.id, buildRequest(draft))}
        >
          {isSaving ? 'Saving…' : 'Save'}
        </button>
      </div>

      <FetchScopeRow
        source={source}
        isSaving={isSaving}
        saveFetchScope={settings.saveFetchScope}
        initialMode={resolveFetchScopeMode(status?.fetch_scope)}
      />
    </div>
  );
}
