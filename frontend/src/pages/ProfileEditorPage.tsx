import { CertificationsList } from '../components/profile/CertificationsList';
import { CvUploadControl } from '../components/profile/CvUploadControl';
import { DealBreakersList } from '../components/profile/DealBreakersList';
import { EducationList } from '../components/profile/EducationList';
import { LanguagesList } from '../components/profile/LanguagesList';
import { PreferencesFields } from '../components/profile/PreferencesFields';
import { RolesList } from '../components/profile/RolesList';
import { SkillsTable } from '../components/profile/SkillsTable';
import { useProfileEditor } from '../hooks/useProfileEditor';
import type { ProfileValidationErrors } from '../lib/profileValidation';
import type { components } from '../api/schema';

type ProfileData = components['schemas']['Profile'];

const NO_ERRORS: ProfileValidationErrors = {
  skills: [],
  pastRoles: [],
  education: [],
  certifications: [],
  languages: [],
};

function withDefaults(profile: ProfileData) {
  return {
    skills: profile.skills ?? [],
    pastRoles: profile.past_roles ?? [],
    education: profile.education ?? [],
    certifications: profile.certifications ?? [],
    languages: profile.languages ?? [],
    dealBreakers: profile.deal_breakers ?? [],
  };
}

export function ProfileEditorPage() {
  const editor = useProfileEditor();
  const errors = editor.attemptedSubmit ? editor.validationErrors : NO_ERRORS;
  const profile = editor.profile;
  const fields = withDefaults(profile);

  if (editor.loading) {
    return (
      <div className="mx-auto flex max-w-3xl flex-col gap-6 p-[var(--spacing-page)]">
        <p className="text-[var(--color-text-muted)]">Loading profile...</p>
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6 p-[var(--spacing-page)]">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">recruFlow — Profile</h1>
          <p className="text-sm text-[var(--color-text-muted)]">
            Upload a CV or edit your profile directly.
          </p>
        </div>
        <span className="card px-3 py-1 text-xs text-[var(--color-text-muted)]">
          {editor.isActive ? 'Active' : 'Draft'}
        </span>
      </header>

      <CvUploadControl onUpload={editor.uploadCv} />

      {editor.error && (
        <div className="card border-[var(--color-danger)] px-4 py-3 text-sm text-[var(--color-danger)]">
          {editor.error}
        </div>
      )}

      <SkillsTable
        skills={fields.skills}
        errors={errors.skills}
        onChange={(skills) => editor.setProfile({ ...profile, skills })}
      />

      <RolesList
        roles={fields.pastRoles}
        errors={errors.pastRoles}
        onChange={(past_roles) => editor.setProfile({ ...profile, past_roles })}
      />

      <EducationList
        education={fields.education}
        errors={errors.education}
        onChange={(education) => editor.setProfile({ ...profile, education })}
      />

      <CertificationsList
        certifications={fields.certifications}
        errors={errors.certifications}
        onChange={(certifications) => editor.setProfile({ ...profile, certifications })}
      />

      <LanguagesList
        languages={fields.languages}
        errors={errors.languages}
        onChange={(languages) => editor.setProfile({ ...profile, languages })}
      />

      <PreferencesFields profile={profile} onChange={editor.setProfile} />

      <DealBreakersList
        dealBreakers={fields.dealBreakers}
        onChange={(deal_breakers) => editor.setProfile({ ...profile, deal_breakers })}
      />

      <div className="flex gap-3">
        <button
          type="button"
          className="btn btn-primary"
          disabled={editor.saving}
          onClick={() => editor.save()}
        >
          Save
        </button>
        <button
          type="button"
          className="btn btn-primary"
          disabled={editor.saving}
          onClick={() => editor.activate()}
        >
          Set as active
        </button>
      </div>
    </div>
  );
}
