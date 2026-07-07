import { useEffect, useState } from 'react';

import type { OfferListFilters } from '../api/offers';
import { FetchNowButton } from '../components/FetchNowButton';
import { GradeFilter } from '../components/GradeFilter';
import { OfferFilters } from '../components/OfferFilters';
import { OfferTable } from '../components/OfferTable';
import { ScoringStatusBanner } from '../components/ScoringStatusBanner';
import { SourceStatusList } from '../components/SourceStatusList';
import { KNOWN_SOURCES } from '../constants';
import { useOffers } from '../hooks/useOffers';
import { useSchedulerStatus } from '../hooks/useSchedulerStatus';
import { useScoringStatus } from '../hooks/useScoringStatus';
import type { Grade } from '../lib/grade';

const PAGE_SIZE = 50;

export function OfferListPage() {
  const [filters, setFilters] = useState<OfferListFilters>({});
  const [minGrade, setMinGrade] = useState<Grade | ''>('');
  const [page, setPage] = useState(0);

  const activeFilters: OfferListFilters = { ...filters, minGrade: minGrade || undefined };
  const { offers, total, loading, error, refetch } = useOffers(activeFilters, {
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  });
  const { sources, refetch: refetchSchedulerStatus } = useSchedulerStatus();
  const { status: scoringStatus } = useScoringStatus();

  const handleIngested = () => {
    refetch();
    refetchSchedulerStatus();
  };

  // A new filter value invalidates whatever page the user was on, so it always
  // jumps back to page one rather than risking an out-of-range offset.
  const handleFiltersChange = (next: OfferListFilters) => {
    setPage(0);
    setFilters(next);
  };

  const handleMinGradeChange = (next: Grade | '') => {
    setPage(0);
    setMinGrade(next);
  };

  // A background scoring run can complete well after the ingest response comes back
  // (BUG16) — this re-pulls the current page each time a run finishes, so grade
  // badges (now inline on each offer, BUG26) can appear without a manual reload.
  useEffect(() => {
    if (scoringStatus?.finished_at) {
      refetch();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scoringStatus?.finished_at]);

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="mx-auto flex w-full max-w-screen-2xl flex-col gap-6 px-4 py-6 sm:px-6 sm:py-8 lg:px-8">
      <header>
        <h1 className="text-2xl font-semibold">recruFlow — Offers</h1>
        <p className="text-sm text-[var(--color-text-muted)]">
          Browse ingested job offers and refresh a source on demand.
        </p>
      </header>

      <SourceStatusList sources={sources} />

      <ScoringStatusBanner status={scoringStatus} />

      <div className="flex flex-wrap gap-3">
        {KNOWN_SOURCES.map((source) => (
          <FetchNowButton
            key={source.id}
            source={source.id}
            label={`Fetch now: ${source.label}`}
            onIngested={handleIngested}
          />
        ))}
      </div>

      <div className="flex flex-wrap items-end gap-4">
        <OfferFilters filters={filters} onChange={handleFiltersChange} />
        <GradeFilter value={minGrade} onChange={handleMinGradeChange} />
      </div>

      {error && (
        <div className="card border-[var(--color-danger)] px-4 py-3 text-sm text-[var(--color-danger)]">
          {error}
        </div>
      )}

      <OfferTable offers={offers} loading={loading} minGrade={minGrade} />

      {total > 0 && (
        <div className="flex items-center justify-between text-sm text-[var(--color-text-muted)]">
          <span>
            {total.toLocaleString('en-US')} offer{total === 1 ? '' : 's'} — page {page + 1} of{' '}
            {pageCount}
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              className="btn"
              disabled={page === 0}
              onClick={() => setPage((current) => Math.max(0, current - 1))}
            >
              Previous
            </button>
            <button
              type="button"
              className="btn"
              disabled={page + 1 >= pageCount}
              onClick={() => setPage((current) => Math.min(pageCount - 1, current + 1))}
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
