import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as offersApi from '../api/offers';
import { useOfferCleanup } from './useOfferCleanup';

vi.mock('../api/offers', () => ({
  previewOfferCleanup: vi.fn(),
  deleteOffers: vi.fn(),
}));

const previewOfferCleanupMock = vi.mocked(offersApi.previewOfferCleanup);
const deleteOffersMock = vi.mocked(offersApi.deleteOffers);

beforeEach(() => {
  previewOfferCleanupMock.mockReset();
  deleteOffersMock.mockReset();
});

describe('useOfferCleanup', () => {
  it('loadPreview success sets preview and clears previewing', async () => {
    previewOfferCleanupMock.mockResolvedValue({ would_delete: 3, would_skip: 1 });

    const { result } = renderHook(() => useOfferCleanup());

    await act(async () => {
      await result.current.loadPreview('2026-01-01T00:00:00Z');
    });

    expect(result.current.preview).toEqual({ wouldDelete: 3, wouldSkip: 1 });
    expect(result.current.previewing).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it('loadPreview failure sets error', async () => {
    previewOfferCleanupMock.mockRejectedValue(new Error('boom'));

    const { result } = renderHook(() => useOfferCleanup());

    await act(async () => {
      await result.current.loadPreview('2026-01-01T00:00:00Z');
    });

    await waitFor(() => expect(result.current.error).toBe('boom'));
    expect(result.current.preview).toBeNull();
    expect(result.current.previewing).toBe(false);
  });

  it('confirmDelete success sets result and clears preview', async () => {
    previewOfferCleanupMock.mockResolvedValue({ would_delete: 2, would_skip: 0 });
    deleteOffersMock.mockResolvedValue({ deleted: 2, skipped: 0 });

    const { result } = renderHook(() => useOfferCleanup());

    await act(async () => {
      await result.current.loadPreview('2026-01-01T00:00:00Z');
    });
    expect(result.current.preview).not.toBeNull();

    await act(async () => {
      await result.current.confirmDelete('2026-01-01T00:00:00Z');
    });

    expect(result.current.result).toEqual({ deleted: 2, skipped: 0 });
    expect(result.current.preview).toBeNull();
    expect(result.current.deleting).toBe(false);
  });

  it('confirmDelete failure sets error and leaves preview untouched', async () => {
    previewOfferCleanupMock.mockResolvedValue({ would_delete: 2, would_skip: 0 });
    deleteOffersMock.mockRejectedValue(new Error('delete failed'));

    const { result } = renderHook(() => useOfferCleanup());

    await act(async () => {
      await result.current.loadPreview('2026-01-01T00:00:00Z');
    });

    await act(async () => {
      await result.current.confirmDelete('2026-01-01T00:00:00Z');
    });

    await waitFor(() => expect(result.current.error).toBe('delete failed'));
    expect(result.current.preview).toEqual({ wouldDelete: 2, wouldSkip: 0 });
    expect(result.current.result).toBeNull();
  });
});
