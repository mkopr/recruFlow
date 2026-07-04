import { describe, expect, it } from 'vitest';

import { boolToSelectValue, selectValueToBool } from './triStateBoolean';

describe('boolToSelectValue', () => {
  it('maps true to "true"', () => {
    expect(boolToSelectValue(true)).toBe('true');
  });

  it('maps false to "false"', () => {
    expect(boolToSelectValue(false)).toBe('false');
  });

  it('maps null to ""', () => {
    expect(boolToSelectValue(null)).toBe('');
  });

  it('maps undefined to ""', () => {
    expect(boolToSelectValue(undefined)).toBe('');
  });
});

describe('selectValueToBool', () => {
  it('maps "true" to true', () => {
    expect(selectValueToBool('true')).toBe(true);
  });

  it('maps "false" to false', () => {
    expect(selectValueToBool('false')).toBe(false);
  });

  it('maps "" to undefined', () => {
    expect(selectValueToBool('')).toBeUndefined();
  });
});
