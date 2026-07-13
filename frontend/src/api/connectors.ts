import { apiClient } from './client';
import type { components } from './schema';

export type ConnectorOption = components['schemas']['ConnectorOption'];

export async function fetchConnectors(): Promise<ConnectorOption[]> {
  const { data, error } = await apiClient.GET('/connectors');

  if (error) {
    throw new Error('failed to load connectors');
  }

  return data;
}
