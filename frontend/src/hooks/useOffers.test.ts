import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as offersApi from '../api/offers';
import type { OfferListFilters } from '../api/offers';
import { useOffers } from './useOffers';

vi.mock('../api/offers', () => ({
  fetchOffers: vi.fn(),
}));

const fetchOffersMock = vi.mocked(offersApi.fetchOffers);

beforeEach(() => {
  fetchOffersMock.mockReset();
  fetchOffersMock.mockResolvedValue([]);
});

describe('useOffers', () => {
  it('fetches immediately on mount, with no debounce delay', async () => {
    const { result } = renderHook(() => useOffers({}));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(fetchOffersMock).toHaveBeenCalledTimes(1);
  });

  it('debounces rapid filter changes into a single fetch (BUG17)', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const { result, rerender } = renderHook((filters: OfferListFilters) => useOffers(filters), {
        initialProps: {} as OfferListFilters,
      });

      await waitFor(() => expect(result.current.loading).toBe(false));
      expect(fetchOffersMock).toHaveBeenCalledTimes(1);

      rerender({ minSalary: 1 });
      rerender({ minSalary: 15 });
      rerender({ minSalary: 150 });

      await vi.advanceTimersByTimeAsync(100);
      expect(fetchOffersMock).toHaveBeenCalledTimes(1);

      await vi.advanceTimersByTimeAsync(300);
      expect(fetchOffersMock).toHaveBeenCalledTimes(2);
      expect(fetchOffersMock).toHaveBeenLastCalledWith({
        source: undefined,
        remote: undefined,
        seniority: undefined,
        minSalary: 150,
      });
    } finally {
      vi.useRealTimers();
    }
  });
});
