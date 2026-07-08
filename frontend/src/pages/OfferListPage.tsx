import { useEffect, useState } from 'react';

import type { OfferListFilters, OfferListSort } from '../api/offers';
import { OfferFilters } from '../components/OfferFilters';
import { OfferTable } from '../components/OfferTable';
import { ScoreFilter } from '../components/ScoreFilter';
import { ScoreNowButton } from '../components/ScoreNowButton';
import { ScoringStatusBanner } from '../components/ScoringStatusBanner';
import { SourceFetchCard } from '../components/SourceFetchCard';
import { KNOWN_SOURCES } from '../constants';
import { useOffers } from '../hooks/useOffers';
import { useSchedulerStatus } from '../hooks/useSchedulerStatus';
import { useScoringStatus } from '../hooks/useScoringStatus';

const PAGE_SIZE = 50;
const DEFAULT_SORT: OfferListSort = { orderBy: 'posted_at', order: 'desc' };

export function OfferListPage() {
  const [filters, setFilters] = useState<OfferListFilters>({});
  const [minScore, setMinScore] = useState<number | ''>('');
  const [page, setPage] = useState(0);
  const [sort, setSort] = useState<OfferListSort>(DEFAULT_SORT);

  const activeFilters: OfferListFilters = {
    ...filters,
    minScore: minScore === '' ? undefined : minScore,
  };
  const { offers, total, loading, error, refetch, updateOffer } = useOffers(activeFilters, sort, {
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

  const handleMinScoreChange = (next: number | '') => {
    setPage(0);
    setMinScore(next);
  };

  // Sorting by score reorders the full backlog server-side (BUG31), so a click
  // resets to page one just like a filter change rather than reshuffling
  // whatever offers happen to already be loaded.
  const handleScoreHeaderClick = () => {
    setPage(0);
    setSort((current) =>
      current.orderBy === 'score_percent'
        ? { orderBy: 'score_percent', order: current.order === 'asc' ? 'desc' : 'asc' }
        : { orderBy: 'score_percent', order: 'asc' },
    );
  };

  // A background scoring run can complete well after the ingest response comes back
  // (BUG16) — this re-pulls the current page each time a run finishes, so score
  // badges (now inline on each offer, BUG26) can appear without a manual reload.
  useEffect(() => {
    if (scoringStatus?.finished_at) {
      refetch();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scoringStatus?.finished_at]);

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const lastFetchedByConnector = new Map(sources.map((source) => [source.connector, source]));

  return (
    <div className="mx-auto flex w-full max-w-screen-2xl flex-col gap-4 px-4 py-6 sm:px-6 sm:py-8 lg:px-8">
      <div className="flex flex-wrap gap-3">
        {KNOWN_SOURCES.map((source) => (
          <SourceFetchCard
            key={source.id}
            source={source.id}
            label={source.label}
            lastFetchedAt={lastFetchedByConnector.get(source.id)?.last_fetched_at ?? null}
            onIngested={handleIngested}
          />
        ))}
        <ScoreNowButton status={scoringStatus} onScored={refetch} />
      </div>

      <ScoringStatusBanner status={scoringStatus} />

      <div className="flex flex-wrap items-end gap-4">
        <OfferFilters filters={filters} onChange={handleFiltersChange} />
        <ScoreFilter value={minScore} onChange={handleMinScoreChange} />
      </div>

      {error && (
        <div className="card border-[var(--color-danger)] px-4 py-3 text-sm text-[var(--color-danger)]">
          {error}
        </div>
      )}

      <OfferTable
        offers={offers}
        loading={loading}
        minScore={minScore}
        sort={sort}
        onScoreHeaderClick={handleScoreHeaderClick}
        onOfferPatched={updateOffer}
      />

      {total > 0 && (
        <div className="flex items-center justify-between text-sm text-[var(--color-text-muted)]">
          <span>
            {total.toLocaleString('en-US')} offer{total === 1 ? '' : 's'}, page {page + 1} of{' '}
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
