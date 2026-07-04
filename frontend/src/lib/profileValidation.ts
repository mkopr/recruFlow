import type { components } from '../api/schema';

type ProfileData = components['schemas']['Profile'];

export interface ProfileValidationErrors {
  skills: boolean[];
  pastRoles: { title: boolean; company: boolean }[];
  education: boolean[];
  certifications: boolean[];
  languages: boolean[];
}

function isBlank(value: string | undefined | null): boolean {
  return (value ?? '').trim() === '';
}

export function validateProfile(profile: ProfileData): ProfileValidationErrors {
  return {
    skills: (profile.skills ?? []).map((skill) => isBlank(skill.name)),
    pastRoles: (profile.past_roles ?? []).map((role) => ({
      title: isBlank(role.title),
      company: isBlank(role.company),
    })),
    education: (profile.education ?? []).map((entry) => isBlank(entry.institution)),
    certifications: (profile.certifications ?? []).map((entry) => isBlank(entry.name)),
    languages: (profile.languages ?? []).map((entry) => isBlank(entry.name)),
  };
}

export function hasValidationErrors(errors: ProfileValidationErrors): boolean {
  return (
    errors.skills.some(Boolean) ||
    errors.pastRoles.some((role) => role.title || role.company) ||
    errors.education.some(Boolean) ||
    errors.certifications.some(Boolean) ||
    errors.languages.some(Boolean)
  );
}
