import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as profileApi from '../api/profile';
import { ProfileEditorPage } from './ProfileEditorPage';

vi.mock('../api/profile', () => ({
  fetchProfile: vi.fn(),
  saveProfile: vi.fn(),
  uploadCv: vi.fn(),
}));

const fetchProfileMock = vi.mocked(profileApi.fetchProfile);
const saveProfileMock = vi.mocked(profileApi.saveProfile);
const uploadCvMock = vi.mocked(profileApi.uploadCv);

function activeProfileResponse(): profileApi.ProfileResponse {
  return {
    id: 1,
    name: 'active-profile',
    status: 'active',
    is_active: true,
    profile: {
      skills: [{ name: 'Python' }],
      past_roles: [],
      education: [],
      certifications: [],
      languages: [],
      deal_breakers: [],
      core_skills: [],
      contract_type_preference: null,
      salary_min: null,
      salary_target: null,
      location_preference: null,
      remote_preference: null,
    },
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  };
}

beforeEach(() => {
  fetchProfileMock.mockReset();
  saveProfileMock.mockReset();
  uploadCvMock.mockReset();
  window.localStorage.clear();
});

describe('ProfileEditorPage', () => {
  it('renders a blank, empty form when fetchProfile resolves null and localStorage is empty', async () => {
    fetchProfileMock.mockResolvedValue(null);

    render(<ProfileEditorPage />);

    await waitFor(() => expect(screen.getByText('Save')).toBeInTheDocument());
    expect(screen.queryByLabelText('Skill 1 name')).not.toBeInTheDocument();
    expect(screen.getByText('Draft')).toBeInTheDocument();
  });

  it('hydrates from a localStorage-cached ProfileResponse without calling fetchProfile', async () => {
    window.localStorage.setItem('recruflow.profileEditor', JSON.stringify(activeProfileResponse()));

    render(<ProfileEditorPage />);

    await waitFor(() => expect(screen.getByLabelText('Skill 1 name')).toHaveValue('Python'));
    expect(fetchProfileMock).not.toHaveBeenCalled();
    expect(screen.getByText('Active')).toBeInTheDocument();
  });

  it("hydrates from fetchProfile's returned active profile when localStorage is empty", async () => {
    fetchProfileMock.mockResolvedValue(activeProfileResponse());

    render(<ProfileEditorPage />);

    await waitFor(() => expect(screen.getByLabelText('Skill 1 name')).toHaveValue('Python'));
    expect(fetchProfileMock).toHaveBeenCalledTimes(1);
  });

  it('blocks Save with a blank required field and highlights it', async () => {
    fetchProfileMock.mockResolvedValue(null);

    render(<ProfileEditorPage />);
    await waitFor(() => expect(screen.getByText('Save')).toBeInTheDocument());

    await userEvent.click(screen.getByText('Add skill'));
    await userEvent.click(screen.getByText('Save'));

    expect(saveProfileMock).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Skill 1 name').className).toContain(
      'border-[var(--color-danger)]',
    );
  });

  it('clicking Save with all required fields filled calls saveProfile with activate: false', async () => {
    fetchProfileMock.mockResolvedValue(activeProfileResponse());
    saveProfileMock.mockResolvedValue(activeProfileResponse());

    render(<ProfileEditorPage />);
    await waitFor(() => expect(screen.getByLabelText('Skill 1 name')).toHaveValue('Python'));

    await userEvent.click(screen.getByText('Save'));

    await waitFor(() =>
      expect(saveProfileMock).toHaveBeenCalledWith(
        expect.anything(),
        expect.objectContaining({ activate: false, profileId: 1 }),
      ),
    );
  });

  it('clicking "Set as active" calls saveProfile with activate: true', async () => {
    fetchProfileMock.mockResolvedValue(activeProfileResponse());
    saveProfileMock.mockResolvedValue(activeProfileResponse());

    render(<ProfileEditorPage />);
    await waitFor(() => expect(screen.getByLabelText('Skill 1 name')).toHaveValue('Python'));

    await userEvent.click(screen.getByText('Set as active'));

    await waitFor(() =>
      expect(saveProfileMock).toHaveBeenCalledWith(
        expect.anything(),
        expect.objectContaining({ activate: true, profileId: 1 }),
      ),
    );
  });

  it('after a successful CV upload, the form re-renders with the draft and Save passes the draft id', async () => {
    fetchProfileMock.mockResolvedValue(null);
    const draft: profileApi.ProfileResponse = {
      ...activeProfileResponse(),
      id: 42,
      is_active: false,
      status: 'draft',
      profile: {
        ...activeProfileResponse().profile,
        skills: [{ name: 'Rust' }],
      },
    };
    uploadCvMock.mockResolvedValue(draft);
    saveProfileMock.mockResolvedValue(draft);

    render(<ProfileEditorPage />);
    await waitFor(() => expect(screen.getByText('Upload CV')).toBeInTheDocument());

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['content'], 'cv.pdf', { type: 'application/pdf' });
    await userEvent.upload(input, file);

    await waitFor(() => expect(screen.getByLabelText('Skill 1 name')).toHaveValue('Rust'));

    await userEvent.click(screen.getByText('Save'));

    await waitFor(() =>
      expect(saveProfileMock).toHaveBeenCalledWith(
        expect.anything(),
        expect.objectContaining({ activate: false, profileId: 42 }),
      ),
    );
  });
});
