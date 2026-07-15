import { apiClient } from './client';
import type { components } from './schema';

export type SourceStatus = components['schemas']['SourceStatus'];
export type FetchRangeUpdateRequest = components['schemas']['FetchRangeUpdateRequest'];
export type FetchScopeUpdateRequest = components['schemas']['FetchScopeUpdateRequest'];

export async function fetchSchedulerStatus(): Promise<SourceStatus[]> {
  const { data, error } = await apiClient.GET('/scheduler/status');

  if (error) {
    throw new Error('failed to load scheduler status');
  }

  return data.sources;
}

export async function updateSourceInterval(source: string, seconds: number): Promise<SourceStatus> {
  const { data, error } = await apiClient.PUT('/scheduler/sources/{source}/interval', {
    params: { path: { source } },
    body: { seconds },
  });

  if (error) {
    throw new Error('failed to update fetch interval');
  }

  return data;
}

export async function updateAllSourceIntervals(seconds: number): Promise<SourceStatus[]> {
  const { data, error } = await apiClient.PUT('/scheduler/sources/interval', {
    body: { seconds },
  });

  if (error) {
    throw new Error('failed to update fetch interval');
  }

  return data.sources;
}

export async function updateSourceFetchRange(
  source: string,
  range: FetchRangeUpdateRequest,
): Promise<SourceStatus> {
  const { data, error } = await apiClient.PUT('/scheduler/sources/{source}/fetch-range', {
    params: { path: { source } },
    body: range,
  });

  if (error) {
    throw new Error('failed to update fetch range');
  }

  return data;
}

export async function updateAllSourceFetchRanges(
  range: FetchRangeUpdateRequest,
): Promise<SourceStatus[]> {
  const { data, error } = await apiClient.PUT('/scheduler/sources/fetch-range', {
    body: range,
  });

  if (error) {
    throw new Error('failed to update fetch range');
  }

  return data.sources;
}

export async function updateSourceFetchScope(
  source: string,
  payload: FetchScopeUpdateRequest,
): Promise<SourceStatus> {
  const { data, error } = await apiClient.PUT('/scheduler/sources/{source}/fetch-scope', {
    params: { path: { source } },
    body: payload,
  });

  if (error) {
    throw new Error('failed to update fetch scope');
  }

  return data;
}

export async function updateSourceAutoFetch(
  source: string,
  enabled: boolean,
): Promise<SourceStatus> {
  const { data, error } = await apiClient.PUT('/scheduler/sources/{source}/auto-fetch', {
    params: { path: { source } },
    body: { enabled },
  });

  if (error) {
    throw new Error('failed to update auto-fetch');
  }

  return data;
}

export async function updateAllSourceAutoFetch(enabled: boolean): Promise<SourceStatus[]> {
  const { data, error } = await apiClient.PUT('/scheduler/sources/auto-fetch', {
    body: { enabled },
  });

  if (error) {
    throw new Error('failed to update auto-fetch');
  }

  return data.sources;
}

export async function updateSourceEnabled(source: string, enabled: boolean): Promise<SourceStatus> {
  const { data, error } = await apiClient.PUT('/scheduler/sources/{source}/enabled', {
    params: { path: { source } },
    body: { enabled },
  });

  if (error) {
    throw new Error('failed to update connector enabled state');
  }

  return data;
}

export async function updateAllSourceEnabled(enabled: boolean): Promise<SourceStatus[]> {
  const { data, error } = await apiClient.PUT('/scheduler/sources/enabled', {
    body: { enabled },
  });

  if (error) {
    throw new Error('failed to update connector enabled state');
  }

  return data.sources;
}
