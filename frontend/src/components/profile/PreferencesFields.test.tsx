import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { components } from '../../api/schema';
import { PreferencesFields } from './PreferencesFields';

type ProfileData = components['schemas']['Profile'];

function baseProfile(): ProfileData {
  return {
    skills: [],
    past_roles: [],
    education: [],
    certifications: [],
    languages: [],
    deal_breakers: [],
    contract_type_preference: null,
    salary_min: null,
    salary_target: null,
    location_preference: null,
    remote_preference: null,
  };
}

describe('PreferencesFields', () => {
  it('changing contract type calls onChange with only that field updated', () => {
    const onChange = vi.fn();
    render(<PreferencesFields profile={baseProfile()} onChange={onChange} />);

    fireEvent.change(screen.getByLabelText('Contract type'), { target: { value: 'B2B' } });

    expect(onChange).toHaveBeenCalledWith({ ...baseProfile(), contract_type_preference: 'B2B' });
  });

  it('changing salary min calls onChange with only that field updated', () => {
    const onChange = vi.fn();
    render(<PreferencesFields profile={baseProfile()} onChange={onChange} />);

    fireEvent.change(screen.getByLabelText('Min salary (PLN)'), {
      target: { value: '15000' },
    });

    expect(onChange).toHaveBeenCalledWith({ ...baseProfile(), salary_min: 15000 });
  });

  it('changing salary target calls onChange with only that field updated', () => {
    const onChange = vi.fn();
    render(<PreferencesFields profile={baseProfile()} onChange={onChange} />);

    fireEvent.change(screen.getByLabelText('Target salary (PLN)'), {
      target: { value: '20000' },
    });

    expect(onChange).toHaveBeenCalledWith({ ...baseProfile(), salary_target: 20000 });
  });

  it('changing location preference calls onChange with only that field updated', () => {
    const onChange = vi.fn();
    render(<PreferencesFields profile={baseProfile()} onChange={onChange} />);

    fireEvent.change(screen.getByLabelText('Location preference'), {
      target: { value: 'Warsaw' },
    });

    expect(onChange).toHaveBeenCalledWith({
      ...baseProfile(),
      location_preference: 'Warsaw',
    });
  });

  it('the remote select round-trips Any/Remote/On-site to null/true/false', async () => {
    const onChange = vi.fn();
    const { rerender } = render(<PreferencesFields profile={baseProfile()} onChange={onChange} />);

    await userEvent.selectOptions(screen.getByLabelText('Remote'), 'true');
    expect(onChange).toHaveBeenLastCalledWith({ ...baseProfile(), remote_preference: true });

    rerender(
      <PreferencesFields
        profile={{ ...baseProfile(), remote_preference: true }}
        onChange={onChange}
      />,
    );
    await userEvent.selectOptions(screen.getByLabelText('Remote'), 'false');
    expect(onChange).toHaveBeenLastCalledWith({ ...baseProfile(), remote_preference: false });

    rerender(
      <PreferencesFields
        profile={{ ...baseProfile(), remote_preference: false }}
        onChange={onChange}
      />,
    );
    await userEvent.selectOptions(screen.getByLabelText('Remote'), '');
    expect(onChange).toHaveBeenLastCalledWith({ ...baseProfile(), remote_preference: null });
  });
});
