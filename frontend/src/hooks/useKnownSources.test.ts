import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as connectorsApi from '../api/connectors';
import { useKnownSources } from './useKnownSources';

vi.mock('../api/connectors', () => ({
  fetchConnectors: vi.fn(),
}));

const fetchConnectorsMock = vi.mocked(connectorsApi.fetchConnectors);

beforeEach(() => {
  fetchConnectorsMock.mockReset();
});

describe('useKnownSources', () => {
  it('calls fetchConnectors once on mount and exposes the resolved array', async () => {
    fetchConnectorsMock.mockResolvedValue([
      {
        id: 'justjoinit',
        label: 'JustJoin.it',
        offer_count: 5,
        scored_count: 2,
        unscored_count: 3,
        supports_fetch_scope: false,
      },
      {
        id: 'solid_jobs',
        label: 'SOLID.Jobs',
        offer_count: 1,
        scored_count: 1,
        unscored_count: 0,
        supports_fetch_scope: false,
      },
    ]);

    const { result } = renderHook(() => useKnownSources());

    await waitFor(() => expect(result.current.sources).toHaveLength(2));
    expect(fetchConnectorsMock).toHaveBeenCalledTimes(1);
  });

  it('leaves sources as an empty array rather than throwing when the fetch rejects', async () => {
    fetchConnectorsMock.mockRejectedValue(new Error('boom'));

    const { result } = renderHook(() => useKnownSources());

    await waitFor(() => expect(fetchConnectorsMock).toHaveBeenCalledTimes(1));
    expect(result.current.sources).toEqual([]);
  });

  it('refetch() re-fetches and replaces sources', async () => {
    fetchConnectorsMock.mockResolvedValueOnce([
      {
        id: 'justjoinit',
        label: 'JustJoin.it',
        offer_count: 5,
        scored_count: 2,
        unscored_count: 3,
        supports_fetch_scope: false,
      },
    ]);

    const { result } = renderHook(() => useKnownSources());
    await waitFor(() => expect(result.current.sources).toHaveLength(1));

    fetchConnectorsMock.mockResolvedValueOnce([
      {
        id: 'solid_jobs',
        label: 'SOLID.Jobs',
        offer_count: 9,
        scored_count: 4,
        unscored_count: 5,
        supports_fetch_scope: false,
      },
    ]);
    result.current.refetch();

    await waitFor(() =>
      expect(result.current.sources).toEqual([
        {
          id: 'solid_jobs',
          label: 'SOLID.Jobs',
          offer_count: 9,
          scored_count: 4,
          unscored_count: 5,
          supports_fetch_scope: false,
        },
      ]),
    );
    expect(fetchConnectorsMock).toHaveBeenCalledTimes(2);
  });
});
