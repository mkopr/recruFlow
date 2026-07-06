import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as scoringConfigApi from '../api/scoringConfig';
import { useScoringConfig } from './useScoringConfig';

vi.mock('../api/scoringConfig', () => ({
  fetchScoringConfig: vi.fn(),
  saveScoringConfig: vi.fn(),
}));

const fetchScoringConfigMock = vi.mocked(scoringConfigApi.fetchScoringConfig);
const saveScoringConfigMock = vi.mocked(scoringConfigApi.saveScoringConfig);

function makeConfig(overrides: Partial<scoringConfigApi.ScoringConfigData> = {}) {
  return { grade_a: 0.85, grade_b: 0.7, grade_c: 0.55, grade_d: 0.4, ...overrides };
}

beforeEach(() => {
  fetchScoringConfigMock.mockReset();
  saveScoringConfigMock.mockReset();
});

describe('useScoringConfig', () => {
  it('fetches and populates config on mount', async () => {
    fetchScoringConfigMock.mockResolvedValue(makeConfig());

    const { result } = renderHook(() => useScoringConfig());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.config).toEqual(makeConfig());
  });

  it('save() calls saveScoringConfig and updates config from the response on a valid payload', async () => {
    fetchScoringConfigMock.mockResolvedValue(makeConfig());
    const updated = makeConfig({ grade_a: 0.9 });
    saveScoringConfigMock.mockResolvedValue(updated);

    const { result } = renderHook(() => useScoringConfig());
    await waitFor(() => expect(result.current.loading).toBe(false));

    const ok = await result.current.save();

    expect(ok).toBe(true);
    expect(saveScoringConfigMock).toHaveBeenCalledWith(makeConfig());
    await waitFor(() => expect(result.current.config).toEqual(updated));
  });

  it('save() does not call saveScoringConfig and returns false when config fails validation', async () => {
    fetchScoringConfigMock.mockResolvedValue(makeConfig({ grade_b: 0.95 }));

    const { result } = renderHook(() => useScoringConfig());
    await waitFor(() => expect(result.current.loading).toBe(false));

    const ok = await result.current.save();

    expect(ok).toBe(false);
    expect(saveScoringConfigMock).not.toHaveBeenCalled();
    await waitFor(() => expect(result.current.attemptedSubmit).toBe(true));
  });

  it("surfaces the thrown error's message into error state when saveScoringConfig rejects", async () => {
    fetchScoringConfigMock.mockResolvedValue(makeConfig());
    saveScoringConfigMock.mockRejectedValue(new Error('descending order violated'));

    const { result } = renderHook(() => useScoringConfig());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await result.current.save();

    await waitFor(() => expect(result.current.error).toBe('descending order violated'));
  });
});
