import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { components } from '../../api/schema';
import { RolesList } from './RolesList';

type PastRole = components['schemas']['PastRole'];

const roles: PastRole[] = [
  {
    title: 'Engineer',
    company: 'Acme',
    start_date: '2020-01',
    end_date: '2022-01',
    description: 'Built things',
  },
];

describe('RolesList', () => {
  it('renders existing entries correctly', () => {
    render(
      <RolesList roles={roles} errors={[{ title: false, company: false }]} onChange={vi.fn()} />,
    );

    expect(screen.getByLabelText('Role 1 title')).toHaveValue('Engineer');
    expect(screen.getByLabelText('Role 1 company')).toHaveValue('Acme');
    expect(screen.getByLabelText('Role 1 start date')).toHaveValue('2020-01');
    expect(screen.getByLabelText('Role 1 end date')).toHaveValue('2022-01');
    expect(screen.getByLabelText('Role 1 description')).toHaveValue('Built things');
  });

  it('"Add role" appends a new blank role', async () => {
    const onChange = vi.fn();
    render(
      <RolesList roles={roles} errors={[{ title: false, company: false }]} onChange={onChange} />,
    );

    await userEvent.click(screen.getByText('Add role'));

    expect(onChange).toHaveBeenCalledWith([
      ...roles,
      { title: '', company: '', start_date: null, end_date: null, description: null },
    ]);
  });

  it('editing a field updates that field immutably', async () => {
    const onChange = vi.fn();
    render(
      <RolesList roles={roles} errors={[{ title: false, company: false }]} onChange={onChange} />,
    );

    await userEvent.type(screen.getByLabelText('Role 1 title'), '!');

    expect(onChange).toHaveBeenLastCalledWith([{ ...roles[0], title: 'Engineer!' }]);
  });

  it('remove excludes a role', async () => {
    const onChange = vi.fn();
    render(
      <RolesList roles={roles} errors={[{ title: false, company: false }]} onChange={onChange} />,
    );

    await userEvent.click(screen.getByText('Remove'));

    expect(onChange).toHaveBeenCalledWith([]);
  });

  it('flags title only when title is missing', () => {
    render(
      <RolesList roles={roles} errors={[{ title: true, company: false }]} onChange={vi.fn()} />,
    );

    expect(screen.getByLabelText('Role 1 title').className).toContain(
      'border-[var(--color-danger)]',
    );
    expect(screen.getByLabelText('Role 1 company').className).not.toContain(
      'border-[var(--color-danger)]',
    );
  });

  it('flags company only when company is missing', () => {
    render(
      <RolesList roles={roles} errors={[{ title: false, company: true }]} onChange={vi.fn()} />,
    );

    expect(screen.getByLabelText('Role 1 company').className).toContain(
      'border-[var(--color-danger)]',
    );
    expect(screen.getByLabelText('Role 1 title').className).not.toContain(
      'border-[var(--color-danger)]',
    );
  });

  it('flags both title and company when both are missing', () => {
    render(
      <RolesList roles={roles} errors={[{ title: true, company: true }]} onChange={vi.fn()} />,
    );

    expect(screen.getByLabelText('Role 1 title').className).toContain(
      'border-[var(--color-danger)]',
    );
    expect(screen.getByLabelText('Role 1 company').className).toContain(
      'border-[var(--color-danger)]',
    );
  });
});
