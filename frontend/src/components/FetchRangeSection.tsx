import { useState } from 'react';

import type { FetchRangeUpdateRequest } from '../api/scheduler';
import { KNOWN_SOURCES } from '../constants';
import { useFetchRangeSettings } from '../hooks/useFetchRangeSettings';

interface RangeDraft {
  mode: 'range' | 'all';
  since: string;
  until: string;
}

function toDatetimeLocalValue(iso: unknown): string {
  if (typeof iso !== 'string' || !iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`;
}

function fromDatetimeLocalValue(value: string): string | null {
  return value ? new Date(value).toISOString() : null;
}

function draftFromFetchRange(fetchRange: Record<string, unknown> | undefined): RangeDraft {
  return {
    mode: fetchRange?.mode === 'all' ? 'all' : 'range',
    since: toDatetimeLocalValue(fetchRange?.since),
    until: toDatetimeLocalValue(fetchRange?.until),
  };
}

function buildRequest(draft: RangeDraft): FetchRangeUpdateRequest {
  if (draft.mode === 'all') {
    return { mode: 'all' };
  }
  return {
    mode: 'range',
    since: fromDatetimeLocalValue(draft.since) ?? undefined,
    until: fromDatetimeLocalValue(draft.until),
  };
}

export function FetchRangeSection() {
  const settings = useFetchRangeSettings();
  const [draftByConnector, setDraftByConnector] = useState<Record<string, RangeDraft>>({});
  const [applyAllDraft, setApplyAllDraft] = useState<RangeDraft>({
    mode: 'range',
    since: '',
    until: '',
  });
  const [applyAllAutoFetch, setApplyAllAutoFetch] = useState(true);

  const draftFor = (
    connector: string,
    fetchRange: Record<string, unknown> | undefined,
  ): RangeDraft => draftByConnector[connector] ?? draftFromFetchRange(fetchRange);

  const setDraft = (connector: string, patch: Partial<RangeDraft>, current: RangeDraft) =>
    setDraftByConnector((prev) => ({ ...prev, [connector]: { ...current, ...patch } }));

  const clearDraft = (connector: string) =>
    setDraftByConnector((prev) => {
      if (!(connector in prev)) return prev;
      const next = { ...prev };
      delete next[connector];
      return next;
    });

  const handleSaveRange = async (connector: string, draft: RangeDraft) => {
    const success = await settings.saveRange(connector, buildRequest(draft));
    if (success) clearDraft(connector);
  };

  const handleSaveRangeAll = async () => {
    const success = await settings.saveRangeAll(buildRequest(applyAllDraft));
    if (success) setDraftByConnector({});
  };

  return (
    <div className="card flex flex-col gap-4 p-4">
      {settings.error && <div className="text-sm text-[var(--color-danger)]">{settings.error}</div>}

      {KNOWN_SOURCES.map((known) => {
        const status = settings.sources.find((source) => source.connector === known.id);
        const draft = draftFor(known.id, status?.fetch_range);
        const isSaving = settings.savingByConnector[known.id] ?? false;
        const autoFetchEnabled = status?.auto_fetch_enabled ?? true;

        return (
          <div
            key={known.id}
            className="flex flex-wrap items-center gap-3 border-b border-[var(--color-border)] pb-3"
          >
            <span className="w-32 text-sm font-medium">{known.label}</span>
            <label className="flex items-center gap-1 text-xs">
              <input
                type="checkbox"
                checked={autoFetchEnabled}
                onChange={(e) => settings.saveAutoFetch(known.id, e.target.checked)}
              />
              Auto-fetch
            </label>
            <select
              className="input w-32"
              value={draft.mode}
              onChange={(e) =>
                setDraft(known.id, { mode: e.target.value as 'range' | 'all' }, draft)
              }
            >
              <option value="range">Date range</option>
              <option value="all">Fetch all</option>
            </select>
            {draft.mode === 'range' && (
              <>
                <input
                  type="datetime-local"
                  className="input"
                  value={draft.since}
                  onChange={(e) => setDraft(known.id, { since: e.target.value }, draft)}
                />
                <span className="text-xs text-[var(--color-text-muted)]">until</span>
                <input
                  type="datetime-local"
                  className="input"
                  value={draft.until}
                  onChange={(e) => setDraft(known.id, { until: e.target.value }, draft)}
                />
                {draft.until === '' && (
                  <span className="text-xs text-[var(--color-text-muted)]">
                    Real-time (no end date) — keeps fetching the freshest postings, no cutoff
                  </span>
                )}
              </>
            )}
            <button
              type="button"
              className="btn"
              disabled={isSaving}
              onClick={() => handleSaveRange(known.id, draft)}
            >
              {isSaving ? 'Saving…' : 'Save'}
            </button>
          </div>
        );
      })}

      <div className="mt-2 flex flex-col gap-3 border-t border-[var(--color-border)] pt-4">
        <div className="flex flex-wrap items-center gap-3">
          <span className="w-32 text-sm font-medium">Apply range to all</span>
          <select
            className="input w-32"
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
              <span className="text-xs text-[var(--color-text-muted)]">until</span>
              <input
                type="datetime-local"
                className="input"
                value={applyAllDraft.until}
                onChange={(e) => setApplyAllDraft((prev) => ({ ...prev, until: e.target.value }))}
              />
              {applyAllDraft.until === '' && (
                <span className="text-xs text-[var(--color-text-muted)]">
                  Real-time (no end date) — keeps fetching the freshest postings, no cutoff
                </span>
              )}
            </>
          )}
          <button type="button" className="btn btn-primary" onClick={handleSaveRangeAll}>
            Apply to all
          </button>
        </div>

        <div className="flex items-center gap-3">
          <span className="w-32 text-sm font-medium">Auto-fetch for all</span>
          <select
            className="input w-32"
            value={applyAllAutoFetch ? 'on' : 'off'}
            onChange={(e) => setApplyAllAutoFetch(e.target.value === 'on')}
          >
            <option value="on">On</option>
            <option value="off">Off</option>
          </select>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => settings.saveAutoFetchAll(applyAllAutoFetch)}
          >
            Apply to all
          </button>
        </div>
      </div>
    </div>
  );
}
