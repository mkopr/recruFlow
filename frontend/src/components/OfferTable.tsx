import { useState } from 'react';

import type { OfferSummary } from '../api/offers';
import { useOfferScoreDetail } from '../hooks/useOfferScoreDetail';
import { gradeRank, isGrade, type Grade } from '../lib/grade';
import { GradeBadge } from './GradeBadge';
import { ScoreDrawer } from './ScoreDrawer';

interface OfferTableProps {
  offers: OfferSummary[];
  loading: boolean;
  minGrade: Grade | '';
}

function formatSalary(offer: OfferSummary): string {
  const { salary_min: min, salary_max: max } = offer;
  const currency = offer.salary_currency ?? 'PLN';

  if (min == null && max == null) return '-';

  const format = (value: number) => value.toLocaleString('en-US');

  if (min != null && max != null) return `${format(min)}-${format(max)} ${currency}`;
  if (min != null) return `${format(min)}+ ${currency}`;
  return `up to ${format(max as number)} ${currency}`;
}

function formatPostedDate(postedAt: string | null): string {
  if (!postedAt) return '-';
  return new Date(postedAt).toLocaleDateString();
}

function sortByPostedDateDesc(offers: OfferSummary[]): OfferSummary[] {
  return [...offers].sort((a, b) => {
    if (a.posted_at === b.posted_at) return 0;
    if (a.posted_at === null) return 1;
    if (b.posted_at === null) return -1;
    return new Date(b.posted_at).getTime() - new Date(a.posted_at).getTime();
  });
}

function sortByGrade(offers: OfferSummary[], direction: 'asc' | 'desc'): OfferSummary[] {
  const scored: Array<{ offer: OfferSummary; rank: number }> = [];
  const unscored: OfferSummary[] = [];

  for (const offer of offers) {
    const grade = offer.grade;
    if (grade != null && isGrade(grade)) {
      scored.push({ offer, rank: gradeRank(grade) });
    } else {
      unscored.push(offer);
    }
  }

  scored.sort((a, b) => (direction === 'asc' ? a.rank - b.rank : b.rank - a.rank));

  return [...scored.map((entry) => entry.offer), ...unscored];
}

function NoOffersEmptyState() {
  return (
    <div className="card flex items-center justify-center py-16 text-[var(--color-text-muted)]">
      No offers yet. Fetch a source above to get started.
    </div>
  );
}

function FilteredEmptyState({ minGrade }: { minGrade: Grade }) {
  return (
    <div className="card flex flex-col items-center justify-center gap-1 py-16 text-center text-[var(--color-text-muted)]">
      <span>No offers meet the minimum grade filter ({minGrade}).</span>
    </div>
  );
}

function getEmptyState(offers: OfferSummary[], minGrade: Grade | '', loading: boolean) {
  if (loading) return null;
  if (offers.length > 0) return null;
  if (minGrade) return <FilteredEmptyState minGrade={minGrade} />;
  return <NoOffersEmptyState />;
}

export function OfferTable({ offers, loading, minGrade }: OfferTableProps) {
  const [selectedOfferId, setSelectedOfferId] = useState<number | null>(null);
  const [gradeSort, setGradeSort] = useState<'asc' | 'desc' | null>(null);
  const { score: selectedScore } = useOfferScoreDetail(selectedOfferId);

  const emptyState = getEmptyState(offers, minGrade, loading);
  if (emptyState) {
    return emptyState;
  }

  const sortedOffers =
    gradeSort !== null ? sortByGrade(offers, gradeSort) : sortByPostedDateDesc(offers);

  const selectedOffer =
    selectedOfferId != null ? offers.find((offer) => offer.id === selectedOfferId) : undefined;

  const handleGradeHeaderClick = () => {
    setGradeSort((current) => (current === 'asc' ? 'desc' : 'asc'));
  };

  return (
    <div className="card max-h-[70vh] overflow-y-auto">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] border-collapse text-left text-sm">
          <thead className="sticky top-0 bg-[var(--color-surface)]">
            <tr className="border-b border-[var(--color-border)] text-[var(--color-text-muted)]">
              <th className="px-4 py-3 font-medium">Title</th>
              <th className="px-4 py-3 font-medium">Company</th>
              <th className="px-4 py-3 font-medium">Source</th>
              <th className="px-4 py-3 font-medium">Salary</th>
              <th className="px-4 py-3 font-medium">Remote</th>
              <th className="px-4 py-3 font-medium">Seniority</th>
              <th className="px-4 py-3 font-medium">Posted</th>
              <th className="px-4 py-3 font-medium">
                <button type="button" className="font-medium" onClick={handleGradeHeaderClick}>
                  Grade
                </button>
              </th>
            </tr>
          </thead>
          <tbody>
            {sortedOffers.map((offer) => (
              <tr
                key={offer.id}
                className="border-b border-[var(--color-border)] last:border-0 hover:bg-[var(--color-surface-hover)]"
              >
                <td className="px-4 py-3">
                  {offer.canonical_url ? (
                    <a
                      href={offer.canonical_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-[var(--color-accent)] hover:underline"
                    >
                      {offer.title}
                    </a>
                  ) : (
                    offer.title
                  )}
                </td>
                <td className="px-4 py-3">{offer.company}</td>
                <td className="px-4 py-3">{offer.source}</td>
                <td className="px-4 py-3">{formatSalary(offer)}</td>
                <td className="px-4 py-3">{offer.remote ? 'Remote' : 'On-site'}</td>
                <td className="px-4 py-3">{offer.seniority ?? '-'}</td>
                <td className="px-4 py-3">{formatPostedDate(offer.posted_at)}</td>
                <td className="px-4 py-3">
                  <GradeBadge grade={offer.grade} onClick={() => setSelectedOfferId(offer.id)} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {selectedOffer != null &&
        (selectedScore != null ? (
          <ScoreDrawer
            score={selectedScore}
            offerTitle={selectedOffer.title}
            onClose={() => setSelectedOfferId(null)}
          />
        ) : (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
            onClick={() => setSelectedOfferId(null)}
          >
            <div className="card p-6 text-sm text-[var(--color-text-muted)]">Loading score…</div>
          </div>
        ))}
    </div>
  );
}
