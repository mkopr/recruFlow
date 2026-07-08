import { useState } from 'react';

import { patchOffer, type OfferSummary } from '../api/offers';
import { useOfferScoreDetail } from '../hooks/useOfferScoreDetail';
import { NotesEditor } from './NotesEditor';
import { ScoreBadge } from './ScoreBadge';
import { ScoreDrawer } from './ScoreDrawer';

interface OfferTableProps {
  offers: OfferSummary[];
  loading: boolean;
  minScore: number | '';
  onOfferPatched: (updated: OfferSummary) => void;
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

function sortByScore(offers: OfferSummary[], direction: 'asc' | 'desc'): OfferSummary[] {
  const scored: OfferSummary[] = [];
  const unscored: OfferSummary[] = [];

  for (const offer of offers) {
    if (offer.score_percent != null) {
      scored.push(offer);
    } else {
      unscored.push(offer);
    }
  }

  scored.sort((a, b) => {
    const diff = (a.score_percent as number) - (b.score_percent as number);
    return direction === 'asc' ? diff : -diff;
  });

  return [...scored, ...unscored];
}

function NoOffersEmptyState() {
  return (
    <div className="card flex items-center justify-center py-16 text-[var(--color-text-muted)]">
      No offers yet. Fetch a source above to get started.
    </div>
  );
}

function FilteredEmptyState({ minScore }: { minScore: number }) {
  return (
    <div className="card flex flex-col items-center justify-center gap-1 py-16 text-center text-[var(--color-text-muted)]">
      <span>No offers meet the minimum score filter ({minScore}%).</span>
    </div>
  );
}

function getEmptyState(offers: OfferSummary[], minScore: number | '', loading: boolean) {
  if (loading) return null;
  if (offers.length > 0) return null;
  if (minScore !== '') return <FilteredEmptyState minScore={minScore} />;
  return <NoOffersEmptyState />;
}

export function OfferTable({ offers, loading, minScore, onOfferPatched }: OfferTableProps) {
  const [selectedOfferId, setSelectedOfferId] = useState<number | null>(null);
  const [scoreSort, setScoreSort] = useState<'asc' | 'desc' | null>(null);
  const [notesOfferId, setNotesOfferId] = useState<number | null>(null);
  const { score: selectedScore } = useOfferScoreDetail(selectedOfferId);

  const emptyState = getEmptyState(offers, minScore, loading);
  if (emptyState) {
    return emptyState;
  }

  const sortedOffers =
    scoreSort !== null ? sortByScore(offers, scoreSort) : sortByPostedDateDesc(offers);

  const selectedOffer =
    selectedOfferId != null ? offers.find((offer) => offer.id === selectedOfferId) : undefined;

  const notesOffer =
    notesOfferId != null ? offers.find((offer) => offer.id === notesOfferId) : undefined;

  const handleScoreHeaderClick = () => {
    setScoreSort((current) => (current === 'asc' ? 'desc' : 'asc'));
  };

  const handleToggleApplied = async (offer: OfferSummary) => {
    const updated = await patchOffer(offer.id, { applied: !offer.applied });
    onOfferPatched(updated);
  };

  const handleToggleHide = async (offer: OfferSummary) => {
    const updated = await patchOffer(offer.id, { hide: !offer.hide });
    onOfferPatched(updated);
  };

  const handleSaveNotes = async (offer: OfferSummary, notes: string) => {
    const updated = await patchOffer(offer.id, { notes });
    onOfferPatched(updated);
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
                <button type="button" className="font-medium" onClick={handleScoreHeaderClick}>
                  Score
                </button>
              </th>
              <th className="px-4 py-3 font-medium">Applied</th>
              <th className="px-4 py-3 font-medium">Notes</th>
              <th className="px-4 py-3 font-medium">Hide</th>
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
                  <ScoreBadge
                    scorePercent={offer.score_percent}
                    onClick={() => setSelectedOfferId(offer.id)}
                  />
                </td>
                <td className="px-4 py-3">
                  <input
                    type="checkbox"
                    aria-label={`Applied to ${offer.title}`}
                    checked={offer.applied}
                    onChange={() => handleToggleApplied(offer)}
                  />
                </td>
                <td className="px-4 py-3">
                  <button
                    type="button"
                    className="btn"
                    aria-label={`Notes for ${offer.title}`}
                    onClick={() => setNotesOfferId(offer.id)}
                  >
                    {offer.notes ? '📝' : '📄'}
                  </button>
                </td>
                <td className="px-4 py-3">
                  <button
                    type="button"
                    className="btn"
                    aria-label={`Hide ${offer.title}`}
                    onClick={() => handleToggleHide(offer)}
                  >
                    {offer.hide ? 'Unhide' : 'Hide'}
                  </button>
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
      {notesOffer != null && (
        <NotesEditor
          offerTitle={notesOffer.title}
          initialNotes={notesOffer.notes}
          onSave={(notes) => handleSaveNotes(notesOffer, notes)}
          onClose={() => setNotesOfferId(null)}
        />
      )}
    </div>
  );
}
