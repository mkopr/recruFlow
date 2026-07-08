import type { ReactNode } from 'react';

import type { Failure, FailureProcess, IngestionFailure, ScoringFailure } from '../api/failures';

export interface FailureColumnContext {
  sourceLabelById: Map<number, string>;
}

export interface FailureColumn {
  key: string;
  label: string;
  render: (row: Failure, context: FailureColumnContext) => ReactNode;
}

function truncate(text: string, max = 80): string {
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

function formatDate(value: string): string {
  return new Date(value).toLocaleString();
}

const ingestionColumns: FailureColumn[] = [
  {
    key: 'source',
    label: 'Source',
    render: (row, { sourceLabelById }) => {
      const sourceId = (row as IngestionFailure).source_id;
      return sourceLabelById.get(sourceId) ?? `#${sourceId}`;
    },
  },
  {
    key: 'failure_type',
    label: 'Failure Type',
    render: (row) => (row as IngestionFailure).failure_type,
  },
  {
    key: 'page',
    label: 'Page',
    render: (row) => (row as IngestionFailure).page ?? '-',
  },
  {
    key: 'occurred_at',
    label: 'Occurred At',
    render: (row) => formatDate(row.occurred_at),
  },
  {
    key: 'error',
    label: 'Error',
    render: (row) => truncate(row.error_message),
  },
];

const scoringColumns: FailureColumn[] = [
  {
    key: 'offer_id',
    label: 'Offer',
    render: (row) => `#${(row as ScoringFailure).offer_id}`,
  },
  {
    key: 'profile_id',
    label: 'Profile',
    render: (row) => `#${(row as ScoringFailure).profile_id}`,
  },
  {
    key: 'failure_type',
    label: 'Failure Type',
    render: (row) => row.failure_type,
  },
  {
    key: 'occurred_at',
    label: 'Occurred At',
    render: (row) => formatDate(row.occurred_at),
  },
  {
    key: 'error',
    label: 'Error',
    render: (row) => truncate(row.error_message),
  },
];

export const failureColumns: Record<FailureProcess, FailureColumn[]> = {
  ingestion: ingestionColumns,
  scoring: scoringColumns,
};
