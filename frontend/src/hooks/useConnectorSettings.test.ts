import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as schedulerApi from '../api/scheduler';
import { useConnectorSettings } from './useConnectorSettings';

vi.mock('../api/scheduler', () => ({
  fetchSchedulerStatus: vi.fn(),
  updateSourceInterval: vi.fn(),
  updateAllSourceIntervals: vi.fn(),
  updateSourceFetchRange: vi.fn(),
  updateAllSourceFetchRanges: vi.fn(),
  updateSourceAutoFetch: vi.fn(),
  updateAllSourceAutoFetch: vi.fn(),
  updateSourceEnabled: vi.fn(),
  updateAllSourceEnabled: vi.fn(),
}));

const fetchSchedulerStatusMock = vi.mocked(schedulerApi.fetchSchedulerStatus);
const updateSourceIntervalMock = vi.mocked(schedulerApi.updateSourceInterval);
const updateAllSourceIntervalsMock = vi.mocked(schedulerApi.updateAllSourceIntervals);
const updateSourceFetchRangeMock = vi.mocked(schedulerApi.updateSourceFetchRange);
const updateAllSourceFetchRangesMock = vi.mocked(schedulerApi.updateAllSourceFetchRanges);
const updateSourceAutoFetchMock = vi.mocked(schedulerApi.updateSourceAutoFetch);
const updateAllSourceAutoFetchMock = vi.mocked(schedulerApi.updateAllSourceAutoFetch);
const updateSourceEnabledMock = vi.mocked(schedulerApi.updateSourceEnabled);
const updateAllSourceEnabledMock = vi.mocked(schedulerApi.updateAllSourceEnabled);

function makeSource(overrides: Partial<schedulerApi.SourceStatus> = {}): schedulerApi.SourceStatus {
  return {
    source_id: 1,
    connector: 'justjoinit',
    name: 'justjoinit',
    schedule: { type: 'interval', seconds: 300 },
    fetch_range: { mode: 'all', since: null, until: null },
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

beforeEach(() => {
  fetchSchedulerStatusMock.mockReset();
  updateSourceIntervalMock.mockReset();
  updateAllSourceIntervalsMock.mockReset();
  updateSourceFetchRangeMock.mockReset();
  updateAllSourceFetchRangesMock.mockReset();
  updateSourceAutoFetchMock.mockReset();
  updateAllSourceAutoFetchMock.mockReset();
  updateSourceEnabledMock.mockReset();
  updateAllSourceEnabledMock.mockReset();
});

describe('useConnectorSettings', () => {
  it('saveInterval calls updateSourceInterval and refetches on success', async () => {
    fetchSchedulerStatusMock.mockResolvedValue([makeSource()]);
    updateSourceIntervalMock.mockResolvedValue(makeSource({ schedule: { seconds: 600 } }));

    const { result } = renderHook(() => useConnectorSettings());
    await waitFor(() => expect(result.current.sources).toHaveLength(1));

    fetchSchedulerStatusMock.mockClear();
    await result.current.saveInterval('justjoinit', 600);

    expect(updateSourceIntervalMock).toHaveBeenCalledWith('justjoinit', 600);
    expect(fetchSchedulerStatusMock).toHaveBeenCalledTimes(1);
  });

  it('saveIntervalAll calls updateAllSourceIntervals once and refetches', async () => {
    fetchSchedulerStatusMock.mockResolvedValue([makeSource()]);
    updateAllSourceIntervalsMock.mockResolvedValue([makeSource({ schedule: { seconds: 900 } })]);

    const { result } = renderHook(() => useConnectorSettings());
    await waitFor(() => expect(result.current.sources).toHaveLength(1));

    fetchSchedulerStatusMock.mockClear();
    await result.current.saveIntervalAll(900);

    expect(updateAllSourceIntervalsMock).toHaveBeenCalledWith(900);
    expect(fetchSchedulerStatusMock).toHaveBeenCalledTimes(1);
  });

  it('saveRange resolves true on success and false on API error', async () => {
    fetchSchedulerStatusMock.mockResolvedValue([makeSource()]);
    const range = { mode: 'range' as const, since: '2026-07-01T00:00:00Z', until: null };
    updateSourceFetchRangeMock.mockResolvedValue(makeSource({ fetch_range: range }));

    const { result } = renderHook(() => useConnectorSettings());
    await waitFor(() => expect(result.current.sources).toHaveLength(1));

    const success = await result.current.saveRange('justjoinit', range);
    expect(success).toBe(true);

    updateSourceFetchRangeMock.mockRejectedValue(new Error('boom'));
    const failure = await result.current.saveRange('justjoinit', range);
    expect(failure).toBe(false);
    await waitFor(() => expect(result.current.error).toBe('boom'));
  });

  it('saveRangeAll resolves true on success and false on API error', async () => {
    fetchSchedulerStatusMock.mockResolvedValue([makeSource()]);
    const range = { mode: 'all' as const };
    updateAllSourceFetchRangesMock.mockResolvedValue([makeSource()]);

    const { result } = renderHook(() => useConnectorSettings());
    await waitFor(() => expect(result.current.sources).toHaveLength(1));

    const success = await result.current.saveRangeAll(range);
    expect(success).toBe(true);

    updateAllSourceFetchRangesMock.mockRejectedValue(new Error('boom'));
    const failure = await result.current.saveRangeAll(range);
    expect(failure).toBe(false);
    await waitFor(() => expect(result.current.error).toBe('boom'));
  });

  it('saveAutoFetch sets savingByConnector during the call and clears it after, refetching on success', async () => {
    fetchSchedulerStatusMock.mockResolvedValue([makeSource()]);
    let resolveUpdate: (value: schedulerApi.SourceStatus) => void = () => {};
    updateSourceAutoFetchMock.mockReturnValue(
      new Promise((resolve) => {
        resolveUpdate = resolve;
      }),
    );

    const { result } = renderHook(() => useConnectorSettings());
    await waitFor(() => expect(result.current.sources).toHaveLength(1));

    const savePromise = result.current.saveAutoFetch('justjoinit', false);
    await waitFor(() => expect(result.current.savingByConnector.justjoinit).toBe(true));

    resolveUpdate(makeSource({ auto_fetch_enabled: false }));
    await savePromise;

    await waitFor(() => expect(result.current.savingByConnector.justjoinit).toBe(false));
    expect(fetchSchedulerStatusMock).toHaveBeenCalled();
  });

  it('a failed saveAutoFetch sets error and leaves state consistent', async () => {
    fetchSchedulerStatusMock.mockResolvedValue([
      makeSource({ connector: 'justjoinit' }),
      makeSource({ connector: 'nofluffjobs' }),
    ]);
    updateSourceAutoFetchMock.mockRejectedValue(new Error('boom'));

    const { result } = renderHook(() => useConnectorSettings());
    await waitFor(() => expect(result.current.sources).toHaveLength(2));

    await result.current.saveAutoFetch('justjoinit', false);

    await waitFor(() => expect(result.current.error).toBe('boom'));
    expect(result.current.savingByConnector.justjoinit).toBe(false);
    expect(result.current.savingByConnector.nofluffjobs).toBeUndefined();
  });

  it('saveAutoFetchAll calls updateAllSourceAutoFetch once and refetches', async () => {
    fetchSchedulerStatusMock.mockResolvedValue([makeSource()]);
    updateAllSourceAutoFetchMock.mockResolvedValue([makeSource({ auto_fetch_enabled: false })]);

    const { result } = renderHook(() => useConnectorSettings());
    await waitFor(() => expect(result.current.sources).toHaveLength(1));

    fetchSchedulerStatusMock.mockClear();
    await result.current.saveAutoFetchAll(false);

    expect(updateAllSourceAutoFetchMock).toHaveBeenCalledWith(false);
    expect(fetchSchedulerStatusMock).toHaveBeenCalledTimes(1);
  });

  it('saveEnabled sets savingByConnector during the call and clears it after, refetching on success', async () => {
    fetchSchedulerStatusMock.mockResolvedValue([makeSource()]);
    let resolveUpdate: (value: schedulerApi.SourceStatus) => void = () => {};
    updateSourceEnabledMock.mockReturnValue(
      new Promise((resolve) => {
        resolveUpdate = resolve;
      }),
    );

    const { result } = renderHook(() => useConnectorSettings());
    await waitFor(() => expect(result.current.sources).toHaveLength(1));

    const savePromise = result.current.saveEnabled('justjoinit', false);
    await waitFor(() => expect(result.current.savingByConnector.justjoinit).toBe(true));

    resolveUpdate(makeSource({ connector_enabled: false }));
    await savePromise;

    await waitFor(() => expect(result.current.savingByConnector.justjoinit).toBe(false));
    expect(fetchSchedulerStatusMock).toHaveBeenCalled();
  });

  it('a failed saveEnabled sets error and leaves state consistent', async () => {
    fetchSchedulerStatusMock.mockResolvedValue([
      makeSource({ connector: 'justjoinit' }),
      makeSource({ connector: 'nofluffjobs' }),
    ]);
    updateSourceEnabledMock.mockRejectedValue(new Error('boom'));

    const { result } = renderHook(() => useConnectorSettings());
    await waitFor(() => expect(result.current.sources).toHaveLength(2));

    await result.current.saveEnabled('justjoinit', false);

    await waitFor(() => expect(result.current.error).toBe('boom'));
    expect(result.current.savingByConnector.justjoinit).toBe(false);
    expect(result.current.savingByConnector.nofluffjobs).toBeUndefined();
  });

  it('saveEnabledAll calls updateAllSourceEnabled once and refetches', async () => {
    fetchSchedulerStatusMock.mockResolvedValue([makeSource()]);
    updateAllSourceEnabledMock.mockResolvedValue([makeSource({ connector_enabled: false })]);

    const { result } = renderHook(() => useConnectorSettings());
    await waitFor(() => expect(result.current.sources).toHaveLength(1));

    fetchSchedulerStatusMock.mockClear();
    await result.current.saveEnabledAll(false);

    expect(updateAllSourceEnabledMock).toHaveBeenCalledWith(false);
    expect(fetchSchedulerStatusMock).toHaveBeenCalledTimes(1);
  });
});
