import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as schedulerApi from '../api/scheduler';
import { useFetchRangeSettings } from './useFetchRangeSettings';

vi.mock('../api/scheduler', () => ({
  fetchSchedulerStatus: vi.fn(),
  updateSourceFetchRange: vi.fn(),
  updateAllSourceFetchRanges: vi.fn(),
  updateSourceAutoFetch: vi.fn(),
  updateAllSourceAutoFetch: vi.fn(),
}));

const fetchSchedulerStatusMock = vi.mocked(schedulerApi.fetchSchedulerStatus);
const updateSourceFetchRangeMock = vi.mocked(schedulerApi.updateSourceFetchRange);
const updateAllSourceFetchRangesMock = vi.mocked(schedulerApi.updateAllSourceFetchRanges);
const updateSourceAutoFetchMock = vi.mocked(schedulerApi.updateSourceAutoFetch);
const updateAllSourceAutoFetchMock = vi.mocked(schedulerApi.updateAllSourceAutoFetch);

function makeSource(overrides: Partial<schedulerApi.SourceStatus> = {}): schedulerApi.SourceStatus {
  return {
    source_id: 1,
    connector: 'justjoinit',
    name: 'justjoinit',
    schedule: { type: 'interval', seconds: 300 },
    fetch_range: { mode: 'range', since: '2026-06-01T00:00:00Z', until: null },
    auto_fetch_enabled: true,
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

beforeEach(() => {
  fetchSchedulerStatusMock.mockReset();
  updateSourceFetchRangeMock.mockReset();
  updateAllSourceFetchRangesMock.mockReset();
  updateSourceAutoFetchMock.mockReset();
  updateAllSourceAutoFetchMock.mockReset();
});

describe('useFetchRangeSettings', () => {
  it('saveRange calls updateSourceFetchRange and refetches on success', async () => {
    fetchSchedulerStatusMock.mockResolvedValue([makeSource()]);
    const range = { mode: 'range' as const, since: '2026-07-01T00:00:00Z', until: null };
    updateSourceFetchRangeMock.mockResolvedValue(makeSource({ fetch_range: range }));

    const { result } = renderHook(() => useFetchRangeSettings());
    await waitFor(() => expect(result.current.sources).toHaveLength(1));

    fetchSchedulerStatusMock.mockClear();
    await result.current.saveRange('justjoinit', range);

    expect(updateSourceFetchRangeMock).toHaveBeenCalledWith('justjoinit', range);
    expect(fetchSchedulerStatusMock).toHaveBeenCalledTimes(1);
  });

  it('saveRangeAll calls updateAllSourceFetchRanges once and refetches', async () => {
    fetchSchedulerStatusMock.mockResolvedValue([makeSource()]);
    const range = { mode: 'all' as const };
    updateAllSourceFetchRangesMock.mockResolvedValue([
      makeSource({ fetch_range: { mode: 'all', since: null, until: null } }),
    ]);

    const { result } = renderHook(() => useFetchRangeSettings());
    await waitFor(() => expect(result.current.sources).toHaveLength(1));

    fetchSchedulerStatusMock.mockClear();
    await result.current.saveRangeAll(range);

    expect(updateAllSourceFetchRangesMock).toHaveBeenCalledTimes(1);
    expect(updateAllSourceFetchRangesMock).toHaveBeenCalledWith(range);
    expect(fetchSchedulerStatusMock).toHaveBeenCalledTimes(1);
  });

  it('saveAutoFetch calls updateSourceAutoFetch and refetches on success', async () => {
    fetchSchedulerStatusMock.mockResolvedValue([makeSource()]);
    updateSourceAutoFetchMock.mockResolvedValue(makeSource({ auto_fetch_enabled: false }));

    const { result } = renderHook(() => useFetchRangeSettings());
    await waitFor(() => expect(result.current.sources).toHaveLength(1));

    fetchSchedulerStatusMock.mockClear();
    await result.current.saveAutoFetch('justjoinit', false);

    expect(updateSourceAutoFetchMock).toHaveBeenCalledWith('justjoinit', false);
    expect(fetchSchedulerStatusMock).toHaveBeenCalledTimes(1);
  });

  it('saveAutoFetchAll calls updateAllSourceAutoFetch once and refetches', async () => {
    fetchSchedulerStatusMock.mockResolvedValue([makeSource()]);
    updateAllSourceAutoFetchMock.mockResolvedValue([makeSource({ auto_fetch_enabled: false })]);

    const { result } = renderHook(() => useFetchRangeSettings());
    await waitFor(() => expect(result.current.sources).toHaveLength(1));

    fetchSchedulerStatusMock.mockClear();
    await result.current.saveAutoFetchAll(false);

    expect(updateAllSourceAutoFetchMock).toHaveBeenCalledTimes(1);
    expect(updateAllSourceAutoFetchMock).toHaveBeenCalledWith(false);
    expect(fetchSchedulerStatusMock).toHaveBeenCalledTimes(1);
  });

  it('a failed saveAutoFetch surfaces an error without corrupting another connector saving state', async () => {
    fetchSchedulerStatusMock.mockResolvedValue([
      makeSource({ connector: 'justjoinit' }),
      makeSource({ connector: 'nofluffjobs' }),
    ]);
    updateSourceAutoFetchMock.mockRejectedValue(new Error('boom'));

    const { result } = renderHook(() => useFetchRangeSettings());
    await waitFor(() => expect(result.current.sources).toHaveLength(2));

    await result.current.saveAutoFetch('justjoinit', false);

    await waitFor(() => expect(result.current.error).toBe('boom'));
    expect(result.current.savingByConnector.justjoinit).toBe(false);
    expect(result.current.savingByConnector.nofluffjobs).toBeUndefined();
  });
});
