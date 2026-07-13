import type { FetchRangeUpdateRequest } from '../api/scheduler';

export interface RangeDraft {
  mode: 'range' | 'all';
  since: string;
  until: string;
}

export function secondsToMinutes(seconds: unknown): number {
  return typeof seconds === 'number' ? seconds / 60 : 5;
}

export function toDatetimeLocalValue(iso: unknown): string {
  if (typeof iso !== 'string' || !iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`;
}

export function fromDatetimeLocalValue(value: string): string | null {
  return value ? new Date(value).toISOString() : null;
}

export function draftFromFetchRange(fetchRange: Record<string, unknown> | undefined): RangeDraft {
  return {
    mode: fetchRange?.mode === 'all' ? 'all' : 'range',
    since: toDatetimeLocalValue(fetchRange?.since),
    until: toDatetimeLocalValue(fetchRange?.until),
  };
}

export function buildRequest(draft: RangeDraft): FetchRangeUpdateRequest {
  if (draft.mode === 'all') {
    return { mode: 'all' };
  }
  return {
    mode: 'range',
    since: fromDatetimeLocalValue(draft.since) ?? undefined,
    until: fromDatetimeLocalValue(draft.until),
  };
}
