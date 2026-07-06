import type { components } from '../api/schema';

type ScoringConfigData = components['schemas']['ScoringConfig'];

export interface ScoringConfigValidationErrors {
  gradeA: boolean;
  gradeB: boolean;
  gradeC: boolean;
  gradeD: boolean;
}

function outOfRange(value: number): boolean {
  return value <= 0 || value > 1;
}

export function validateScoringConfig(config: ScoringConfigData): ScoringConfigValidationErrors {
  const { grade_a: gradeA, grade_b: gradeB, grade_c: gradeC, grade_d: gradeD } = config;

  return {
    gradeA: outOfRange(gradeA),
    gradeB: outOfRange(gradeB) || gradeB >= gradeA,
    gradeC: outOfRange(gradeC) || gradeC >= gradeB,
    gradeD: outOfRange(gradeD) || gradeD >= gradeC,
  };
}

export function hasValidationErrors(errors: ScoringConfigValidationErrors): boolean {
  return errors.gradeA || errors.gradeB || errors.gradeC || errors.gradeD;
}
