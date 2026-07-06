export const GRADE_ORDER = ['A', 'B', 'C', 'D', 'F'] as const;

export type Grade = (typeof GRADE_ORDER)[number];

export function isGrade(value: string): value is Grade {
  return (GRADE_ORDER as readonly string[]).includes(value);
}

export function gradeRank(grade: Grade): number {
  return GRADE_ORDER.indexOf(grade);
}

export function meetsMinimumGrade(grade: Grade, minGrade: Grade): boolean {
  return gradeRank(grade) <= gradeRank(minGrade);
}

export const GRADE_BADGE_CLASS: Record<Grade, string> = {
  A: 'badge-grade-a',
  B: 'badge-grade-b',
  C: 'badge-grade-c',
  D: 'badge-grade-d',
  F: 'badge-grade-f',
};
