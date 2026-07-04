import { describe, expect, it } from 'vitest';

import type { components } from '../api/schema';
import { hasValidationErrors, validateProfile } from './profileValidation';

type ProfileData = components['schemas']['Profile'];

function emptyProfile(): ProfileData {
  return {
    skills: [],
    past_roles: [],
    education: [],
    certifications: [],
    languages: [],
    deal_breakers: [],
  };
}

describe('validateProfile', () => {
  it('produces all-false errors for a valid profile with all required sub-fields filled', () => {
    const profile: ProfileData = {
      ...emptyProfile(),
      skills: [{ name: 'Python' }],
      past_roles: [{ title: 'Engineer', company: 'Acme' }],
      education: [{ institution: 'MIT' }],
      certifications: [{ name: 'AWS SAA' }],
      languages: [{ name: 'English' }],
    };

    const errors = validateProfile(profile);

    expect(errors.skills).toEqual([false]);
    expect(errors.pastRoles).toEqual([{ title: false, company: false }]);
    expect(errors.education).toEqual([false]);
    expect(errors.certifications).toEqual([false]);
    expect(errors.languages).toEqual([false]);
    expect(hasValidationErrors(errors)).toBe(false);
  });

  it('flags a skill with a blank name and one with a whitespace-only name', () => {
    const profile: ProfileData = {
      ...emptyProfile(),
      skills: [{ name: '' }, { name: '   ' }, { name: 'Go' }],
    };

    const errors = validateProfile(profile);

    expect(errors.skills).toEqual([true, true, false]);
  });

  it('flags a past role missing only title', () => {
    const profile: ProfileData = {
      ...emptyProfile(),
      past_roles: [{ title: '', company: 'Acme' }],
    };

    expect(validateProfile(profile).pastRoles).toEqual([{ title: true, company: false }]);
  });

  it('flags a past role missing only company', () => {
    const profile: ProfileData = {
      ...emptyProfile(),
      past_roles: [{ title: 'Engineer', company: '' }],
    };

    expect(validateProfile(profile).pastRoles).toEqual([{ title: false, company: true }]);
  });

  it('flags a past role missing both title and company', () => {
    const profile: ProfileData = {
      ...emptyProfile(),
      past_roles: [{ title: '', company: '' }],
    };

    expect(validateProfile(profile).pastRoles).toEqual([{ title: true, company: true }]);
  });

  it('flags an education entry with a blank institution', () => {
    const profile: ProfileData = {
      ...emptyProfile(),
      education: [{ institution: '' }],
    };

    expect(validateProfile(profile).education).toEqual([true]);
  });

  it('flags a certification with a blank name', () => {
    const profile: ProfileData = {
      ...emptyProfile(),
      certifications: [{ name: '' }],
    };

    expect(validateProfile(profile).certifications).toEqual([true]);
  });

  it('flags a language with a blank name', () => {
    const profile: ProfileData = {
      ...emptyProfile(),
      languages: [{ name: '' }],
    };

    expect(validateProfile(profile).languages).toEqual([true]);
  });

  it('produces empty error arrays and no errors for an entirely empty profile', () => {
    const errors = validateProfile(emptyProfile());

    expect(errors).toEqual({
      skills: [],
      pastRoles: [],
      education: [],
      certifications: [],
      languages: [],
    });
    expect(hasValidationErrors(errors)).toBe(false);
  });
});

describe('hasValidationErrors', () => {
  it('returns false for an all-clear ProfileValidationErrors object', () => {
    expect(
      hasValidationErrors({
        skills: [false, false],
        pastRoles: [{ title: false, company: false }],
        education: [false],
        certifications: [false],
        languages: [false],
      }),
    ).toBe(false);
  });

  it('returns true if any single nested boolean anywhere is true', () => {
    expect(
      hasValidationErrors({
        skills: [false],
        pastRoles: [{ title: false, company: true }],
        education: [false],
        certifications: [false],
        languages: [false],
      }),
    ).toBe(true);
  });
});
