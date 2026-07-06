import { useState } from 'react';

import type { OfferSummary } from '../api/offers';
import type { MatchScoreResponse } from '../api/offerScore';
import { gradeRank, isGrade, meetsMinimumGrade, type Grade } from '../lib/grade';
import { GradeBadge } from './GradeBadge';
import { ScoreDrawer } from './ScoreDrawer';

interface OfferTableProps {
  offers: OfferSummary[];
  loading: boolean;
  scores: Record<number, MatchScoreResponse | null>;
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

function filterByMinGrade(
  offers: OfferSummary[],
  scores: Record<number, MatchScoreResponse | null>,
  minGrade: Grade | '',
): OfferSummary[] {
  if (minGrade === '') return offers;

  return offers.filter((offer) => {
    const score = scores[offer.id];
    return score != null && isGrade(score.grade) && meetsMinimumGrade(score.grade, minGrade);
  });
}

function sortByGrade(
  offers: OfferSummary[],
  scores: Record<number, MatchScoreResponse | null>,
  direction: 'asc' | 'desc',
): OfferSummary[] {
  const scored: Array<{ offer: OfferSummary; rank: number }> = [];
  const unscored: OfferSummary[] = [];

  for (const offer of offers) {
    const grade = scores[offer.id]?.grade;
    if (grade != null && isGrade(grade)) {
      scored.push({ offer, rank: gradeRank(grade) });
    } else {
      unscored.push(offer);
    }
  }

  scored.sort((a, b) => (direction === 'asc' ? a.rank - b.rank : b.rank - a.rank));

  return [...scored.map((entry) => entry.offer), ...unscored];
}

export function OfferTable({ offers, loading, scores, minGrade }: OfferTableProps) {
  const [selectedOfferId, setSelectedOfferId] = useState<number | null>(null);
  const [gradeSort, setGradeSort] = useState<'asc' | 'desc' | null>(null);

  if (offers.length === 0 && !loading) {
    return (
      <div className="card flex items-center justify-center py-16 text-[var(--color-text-muted)]">
        No offers yet — try Fetch now above.
      </div>
    );
  }

  const filteredOffers = filterByMinGrade(offers, scores, minGrade);
  const sortedOffers =
    gradeSort !== null
      ? sortByGrade(filteredOffers, scores, gradeSort)
      : sortByPostedDateDesc(filteredOffers);

  const selectedScore = selectedOfferId != null ? scores[selectedOfferId] : null;
  const selectedOffer =
    selectedOfferId != null ? offers.find((offer) => offer.id === selectedOfferId) : undefined;

  const handleGradeHeaderClick = () => {
    setGradeSort((current) => (current === 'asc' ? 'desc' : 'asc'));
  };

  return (
    <div className="card max-h-[70vh] overflow-y-auto">
      <table className="w-full border-collapse text-left text-sm">
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
                <GradeBadge
                  grade={scores[offer.id]?.grade}
                  onClick={scores[offer.id] ? () => setSelectedOfferId(offer.id) : undefined}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {selectedScore != null && selectedOffer != null && (
        <ScoreDrawer
          score={selectedScore}
          offerTitle={selectedOffer.title}
          onClose={() => setSelectedOfferId(null)}
        />
      )}
    </div>
  );
}
