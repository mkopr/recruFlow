export function boolToSelectValue(value: boolean | null | undefined): '' | 'true' | 'false' {
  if (value === undefined || value === null) return '';
  return value ? 'true' : 'false';
}

export function selectValueToBool(value: string): boolean | undefined {
  if (value === 'true') return true;
  if (value === 'false') return false;
  return undefined;
}
