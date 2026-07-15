import { useState } from 'react';

import { patchOffer, type OfferListSort, type OfferSummary } from '../api/offers';
import { useOfferScoreDetail } from '../hooks/useOfferScoreDetail';
import { loadScoreAlertPrefs } from '../lib/scoreAlertPrefs';
import { NotesEditor } from './NotesEditor';
import { ScoreBadge } from './ScoreBadge';
import { ScoreDrawer } from './ScoreDrawer';

interface OfferTableProps {
  offers: OfferSummary[];
  loading: boolean;
  minScore: number | '';
  sort: OfferListSort;
  onScoreHeaderClick: () => void;
  onPostedHeaderClick: () => void;
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

function isHighlighted(offer: OfferSummary, minScorePercent: number): boolean {
  return (
    offer.canonical_url != null &&
    offer.score_percent != null &&
    offer.score_percent >= minScorePercent &&
    offer.link_opened_at == null
  );
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

function sortIndicator(sort: OfferListSort, column: OfferListSort['orderBy']): string {
  if (sort.orderBy !== column) return '';
  return sort.order === 'asc' ? ' ▲' : ' ▼';
}

export function OfferTable({
  offers,
  loading,
  minScore,
  sort,
  onScoreHeaderClick,
  onPostedHeaderClick,
  onOfferPatched,
}: OfferTableProps) {
  const [selectedOfferId, setSelectedOfferId] = useState<number | null>(null);
  const [notesOfferId, setNotesOfferId] = useState<number | null>(null);
  const { score: selectedScore } = useOfferScoreDetail(selectedOfferId);
  const { minScorePercent } = loadScoreAlertPrefs();

  const emptyState = getEmptyState(offers, minScore, loading);
  if (emptyState) {
    return emptyState;
  }

  const selectedOffer =
    selectedOfferId != null ? offers.find((offer) => offer.id === selectedOfferId) : undefined;

  const notesOffer =
    notesOfferId != null ? offers.find((offer) => offer.id === notesOfferId) : undefined;

  const scoreSortIndicator = sortIndicator(sort, 'score_percent');
  const postedSortIndicator = sortIndicator(sort, 'posted_at');

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

  const handleOpenLink = (offer: OfferSummary) => {
    if (offer.link_opened_at != null) return;
    onOfferPatched({ ...offer, link_opened_at: new Date().toISOString() });
    void patchOffer(offer.id, { link_opened: true }).catch(() => {});
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
              <th className="px-4 py-3 font-medium">
                <button type="button" className="font-medium" onClick={onPostedHeaderClick}>
                  Posted{postedSortIndicator}
                </button>
              </th>
              <th className="px-4 py-3 font-medium">
                <button type="button" className="font-medium" onClick={onScoreHeaderClick}>
                  Score{scoreSortIndicator}
                </button>
              </th>
              <th className="px-4 py-3 font-medium">Applied</th>
              <th className="px-4 py-3 font-medium">Notes</th>
              <th className="px-4 py-3 font-medium">Hide</th>
            </tr>
          </thead>
          <tbody>
            {offers.map((offer) => (
              <tr
                key={offer.id}
                className={`border-b border-[var(--color-border)] last:border-0 hover:bg-[var(--color-surface-hover)] ${
                  isHighlighted(offer, minScorePercent) ? 'card-accent' : ''
                }`}
              >
                <td className="px-4 py-3">
                  {offer.canonical_url ? (
                    <a
                      href={offer.canonical_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-[var(--color-accent)] hover:underline"
                      onClick={() => handleOpenLink(offer)}
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
