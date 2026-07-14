const STORAGE_KEY = 'recruflow.connectorSettingsTab';

export function loadSelectedConnectorTab(): string | null {
  return localStorage.getItem(STORAGE_KEY);
}

export function saveSelectedConnectorTab(connectorId: string): void {
  localStorage.setItem(STORAGE_KEY, connectorId);
}
