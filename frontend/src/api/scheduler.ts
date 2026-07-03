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
