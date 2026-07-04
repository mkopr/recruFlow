import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { components } from '../../api/schema';
import { CertificationsList } from './CertificationsList';

type Certification = components['schemas']['Certification'];

const certifications: Certification[] = [{ name: 'AWS SAA', issuer: 'AWS', year: 2022 }];

describe('CertificationsList', () => {
  it('renders existing entries correctly', () => {
    render(
      <CertificationsList certifications={certifications} errors={[false]} onChange={vi.fn()} />,
    );

    expect(screen.getByLabelText('Certification 1 name')).toHaveValue('AWS SAA');
    expect(screen.getByLabelText('Certification 1 issuer')).toHaveValue('AWS');
    expect(screen.getByLabelText('Certification 1 year')).toHaveValue(2022);
  });

  it('"Add certification" appends a new blank entry', async () => {
    const onChange = vi.fn();
    render(
      <CertificationsList certifications={certifications} errors={[false]} onChange={onChange} />,
    );

    await userEvent.click(screen.getByText('Add certification'));

    expect(onChange).toHaveBeenCalledWith([
      ...certifications,
      { name: '', issuer: null, year: null },
    ]);
  });

  it('editing a field updates it immutably', async () => {
    const onChange = vi.fn();
    render(
      <CertificationsList certifications={certifications} errors={[false]} onChange={onChange} />,
    );

    await userEvent.type(screen.getByLabelText('Certification 1 name'), '!');

    expect(onChange).toHaveBeenLastCalledWith([{ ...certifications[0], name: 'AWS SAA!' }]);
  });

  it('remove excludes an entry', async () => {
    const onChange = vi.fn();
    render(
      <CertificationsList certifications={certifications} errors={[false]} onChange={onChange} />,
    );

    await userEvent.click(screen.getByText('Remove'));

    expect(onChange).toHaveBeenCalledWith([]);
  });

  it('highlights name for a flagged entry', () => {
    render(
      <CertificationsList certifications={certifications} errors={[true]} onChange={vi.fn()} />,
    );

    expect(screen.getByLabelText('Certification 1 name').className).toContain(
      'border-[var(--color-danger)]',
    );
  });
});
