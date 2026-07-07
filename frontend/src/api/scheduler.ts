import { apiClient } from './client';
import type { components } from './schema';

export type SourceStatus = components['schemas']['SourceStatus'];

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
