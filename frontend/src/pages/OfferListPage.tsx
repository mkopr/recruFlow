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
import { useOfferScores } from '../hooks/useOfferScores';
import { useSchedulerStatus } from '../hooks/useSchedulerStatus';
import { useScoringStatus } from '../hooks/useScoringStatus';
import type { Grade } from '../lib/grade';

export function OfferListPage() {
  const [filters, setFilters] = useState<OfferListFilters>({});
  const [minGrade, setMinGrade] = useState<Grade | ''>('');
  const { offers, loading, error, refetch } = useOffers(filters);
  const { scores, refetch: refetchScores } = useOfferScores(offers.map((offer) => offer.id));
  const { sources, refetch: refetchSchedulerStatus } = useSchedulerStatus();
  const { status: scoringStatus } = useScoringStatus();

  const handleIngested = () => {
    refetch();
    refetchSchedulerStatus();
  };

  // A background scoring run can complete well after the ingest response comes back
  // (BUG16) — this re-pulls scores for the currently-listed offers each time a run
  // finishes, so a grade badge can appear without the user reloading the page.
  useEffect(() => {
    if (scoringStatus?.finished_at) {
      refetchScores();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scoringStatus?.finished_at]);

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6 p-[var(--spacing-page)]">
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
        <OfferFilters filters={filters} onChange={setFilters} />
        <GradeFilter value={minGrade} onChange={setMinGrade} />
      </div>

      {error && (
        <div className="card border-[var(--color-danger)] px-4 py-3 text-sm text-[var(--color-danger)]">
          {error}
        </div>
      )}

      <OfferTable offers={offers} loading={loading} scores={scores} minGrade={minGrade} />
    </div>
  );
}
