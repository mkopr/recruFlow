import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as schedulerApi from '../api/scheduler';
import { useFetchCadence } from './useFetchCadence';

vi.mock('../api/scheduler', () => ({
  fetchSchedulerStatus: vi.fn(),
  updateSourceInterval: vi.fn(),
  updateAllSourceIntervals: vi.fn(),
}));

const fetchSchedulerStatusMock = vi.mocked(schedulerApi.fetchSchedulerStatus);
const updateSourceIntervalMock = vi.mocked(schedulerApi.updateSourceInterval);
const updateAllSourceIntervalsMock = vi.mocked(schedulerApi.updateAllSourceIntervals);

function makeSource(overrides: Partial<schedulerApi.SourceStatus> = {}): schedulerApi.SourceStatus {
  return {
    source_id: 1,
    connector: 'justjoinit',
    name: 'justjoinit',
    schedule: { type: 'interval', seconds: 300 },
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
});

describe('useFetchCadence', () => {
  it('saveOne calls updateSourceInterval and refetches on success', async () => {
    fetchSchedulerStatusMock.mockResolvedValue([makeSource()]);
    updateSourceIntervalMock.mockResolvedValue(makeSource({ schedule: { seconds: 600 } }));

    const { result } = renderHook(() => useFetchCadence());
    await waitFor(() => expect(result.current.sources).toHaveLength(1));

    fetchSchedulerStatusMock.mockClear();
    await result.current.saveOne('justjoinit', 600);

    expect(updateSourceIntervalMock).toHaveBeenCalledWith('justjoinit', 600);
    expect(fetchSchedulerStatusMock).toHaveBeenCalledTimes(1);
  });

  it('saveAll calls updateAllSourceIntervals once and refetches', async () => {
    fetchSchedulerStatusMock.mockResolvedValue([makeSource()]);
    updateAllSourceIntervalsMock.mockResolvedValue([makeSource({ schedule: { seconds: 900 } })]);

    const { result } = renderHook(() => useFetchCadence());
    await waitFor(() => expect(result.current.sources).toHaveLength(1));

    fetchSchedulerStatusMock.mockClear();
    await result.current.saveAll(900);

    expect(updateAllSourceIntervalsMock).toHaveBeenCalledTimes(1);
    expect(updateAllSourceIntervalsMock).toHaveBeenCalledWith(900);
    expect(fetchSchedulerStatusMock).toHaveBeenCalledTimes(1);
  });

  it('a failed saveOne surfaces an error without touching other rows saving state', async () => {
    fetchSchedulerStatusMock.mockResolvedValue([
      makeSource({ connector: 'justjoinit' }),
      makeSource({ connector: 'nofluffjobs' }),
    ]);
    updateSourceIntervalMock.mockRejectedValue(new Error('boom'));

    const { result } = renderHook(() => useFetchCadence());
    await waitFor(() => expect(result.current.sources).toHaveLength(2));

    await result.current.saveOne('justjoinit', 600);

    await waitFor(() => expect(result.current.error).toBe('boom'));
    expect(result.current.saving.justjoinit).toBe(false);
    expect(result.current.saving.nofluffjobs).toBeUndefined();
  });
});
