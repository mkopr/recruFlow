import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { components } from '../../api/schema';
import { EducationList } from './EducationList';

type Education = components['schemas']['Education'];

const education: Education[] = [
  {
    institution: 'MIT',
    degree: 'BSc',
    field_of_study: 'CS',
    start_date: '2015-09',
    end_date: '2019-06',
  },
];

describe('EducationList', () => {
  it('renders existing entries correctly', () => {
    render(<EducationList education={education} errors={[false]} onChange={vi.fn()} />);

    expect(screen.getByLabelText('Education 1 institution')).toHaveValue('MIT');
    expect(screen.getByLabelText('Education 1 degree')).toHaveValue('BSc');
    expect(screen.getByLabelText('Education 1 field of study')).toHaveValue('CS');
  });

  it('"Add education" appends a new blank entry', async () => {
    const onChange = vi.fn();
    render(<EducationList education={education} errors={[false]} onChange={onChange} />);

    await userEvent.click(screen.getByText('Add education'));

    expect(onChange).toHaveBeenCalledWith([
      ...education,
      { institution: '', degree: null, field_of_study: null, start_date: null, end_date: null },
    ]);
  });

  it('editing a field updates it immutably', async () => {
    const onChange = vi.fn();
    render(<EducationList education={education} errors={[false]} onChange={onChange} />);

    await userEvent.type(screen.getByLabelText('Education 1 institution'), '!');

    expect(onChange).toHaveBeenLastCalledWith([{ ...education[0], institution: 'MIT!' }]);
  });

  it('remove excludes an entry', async () => {
    const onChange = vi.fn();
    render(<EducationList education={education} errors={[false]} onChange={onChange} />);

    await userEvent.click(screen.getByText('Remove'));

    expect(onChange).toHaveBeenCalledWith([]);
  });

  it('highlights institution for a flagged entry', () => {
    render(<EducationList education={education} errors={[true]} onChange={vi.fn()} />);

    expect(screen.getByLabelText('Education 1 institution').className).toContain(
      'border-[var(--color-danger)]',
    );
  });
});
