import { useState } from 'react';

import type { OfferListFilters } from '../api/offers';
import { FetchNowButton } from '../components/FetchNowButton';
import { OfferFilters } from '../components/OfferFilters';
import { OfferTable } from '../components/OfferTable';
import { KNOWN_SOURCES } from '../constants';
import { useOffers } from '../hooks/useOffers';

export function OfferListPage() {
  const [filters, setFilters] = useState<OfferListFilters>({});
  const { offers, loading, error, refetch } = useOffers(filters);

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6 p-[var(--spacing-page)]">
      <header>
        <h1 className="text-2xl font-semibold">recruFlow — Offers</h1>
        <p className="text-sm text-[var(--color-text-muted)]">
          Browse ingested job offers and refresh a source on demand.
        </p>
      </header>

      <div className="flex flex-wrap gap-3">
        {KNOWN_SOURCES.map((source) => (
          <FetchNowButton
            key={source.id}
            source={source.id}
            label={`Fetch now: ${source.label}`}
            onIngested={refetch}
          />
        ))}
      </div>

      <OfferFilters filters={filters} onChange={setFilters} />

      {error && (
        <div className="card border-[var(--color-danger)] px-4 py-3 text-sm text-[var(--color-danger)]">
          {error}
        </div>
      )}

      <OfferTable offers={offers} loading={loading} />
    </div>
  );
}
