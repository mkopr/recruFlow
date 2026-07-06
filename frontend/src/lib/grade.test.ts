import { describe, expect, it } from 'vitest';

import { GRADE_ORDER, gradeRank, isGrade, meetsMinimumGrade } from './grade';

describe('GRADE_ORDER', () => {
  it('lists all five grades best to worst', () => {
    expect(GRADE_ORDER).toEqual(['A', 'B', 'C', 'D', 'F']);
  });
});

describe('gradeRank', () => {
  it('orders A ahead of F', () => {
    expect(gradeRank('A')).toBeLessThan(gradeRank('F'));
  });
});

describe('meetsMinimumGrade', () => {
  it('returns true when the grade equals the minimum', () => {
    expect(meetsMinimumGrade('B', 'B')).toBe(true);
  });

  it('returns true when the grade is better than the minimum', () => {
    expect(meetsMinimumGrade('A', 'C')).toBe(true);
  });

  it('returns false when the grade is worse than the minimum', () => {
    expect(meetsMinimumGrade('D', 'B')).toBe(false);
  });
});

describe('isGrade', () => {
  it('accepts only the five known uppercase letters', () => {
    expect(isGrade('A')).toBe(true);
    expect(isGrade('E')).toBe(false);
    expect(isGrade('a')).toBe(false);
    expect(isGrade('')).toBe(false);
  });
});
