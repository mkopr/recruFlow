import { describe, expect, it } from 'vitest';

import type { components } from '../api/schema';
import { hasValidationErrors, validateScoringConfig } from './scoringConfigValidation';

type ScoringConfigData = components['schemas']['ScoringConfig'];

function validConfig(): ScoringConfigData {
  return { grade_a: 0.85, grade_b: 0.7, grade_c: 0.55, grade_d: 0.4 };
}

describe('validateScoringConfig', () => {
  it('produces all-false errors for a correctly descending, in-range config', () => {
    const errors = validateScoringConfig(validConfig());

    expect(errors).toEqual({ gradeA: false, gradeB: false, gradeC: false, gradeD: false });
    expect(hasValidationErrors(errors)).toBe(false);
  });

  it('flags grade_b when grade_b >= grade_a', () => {
    const config = { ...validConfig(), grade_b: 0.9 };

    expect(validateScoringConfig(config).gradeB).toBe(true);
  });

  it('flags grade_c when grade_c >= grade_b', () => {
    const config = { ...validConfig(), grade_c: 0.8 };

    expect(validateScoringConfig(config).gradeC).toBe(true);
  });

  it('flags grade_d when grade_d >= grade_c', () => {
    const config = { ...validConfig(), grade_d: 0.6 };

    expect(validateScoringConfig(config).gradeD).toBe(true);
  });

  it('flags grade_d when grade_d <= 0', () => {
    const config = { ...validConfig(), grade_d: 0 };

    expect(validateScoringConfig(config).gradeD).toBe(true);
  });

  it('flags any field greater than 1', () => {
    const config = { ...validConfig(), grade_a: 1.01 };

    expect(validateScoringConfig(config).gradeA).toBe(true);
  });
});

describe('hasValidationErrors', () => {
  it('returns false for an all-clear errors object', () => {
    expect(
      hasValidationErrors({ gradeA: false, gradeB: false, gradeC: false, gradeD: false }),
    ).toBe(false);
  });

  it('returns true if any single field is flagged', () => {
    expect(hasValidationErrors({ gradeA: false, gradeB: true, gradeC: false, gradeD: false })).toBe(
      true,
    );
  });
});
