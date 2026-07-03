import type { OfferSummary } from '../api/offers';

interface OfferTableProps {
  offers: OfferSummary[];
  loading: boolean;
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

export function OfferTable({ offers, loading }: OfferTableProps) {
  if (offers.length === 0 && !loading) {
    return (
      <div className="card flex items-center justify-center py-16 text-[var(--color-text-muted)]">
        No offers yet — try Fetch now above.
      </div>
    );
  }

  const sortedOffers = sortByPostedDateDesc(offers);

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
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
