export interface SourceOption {
  id: string;
  label: string;
}

export const KNOWN_SOURCES: SourceOption[] = [
  { id: 'solid_jobs', label: 'SOLID.Jobs' },
  { id: 'justjoinit', label: 'JustJoin.it' },
  { id: 'nofluffjobs', label: 'NoFluffJobs' },
];

export const SENIORITY_LEVELS: string[] = ['junior', 'mid', 'senior', 'lead', 'expert'];
