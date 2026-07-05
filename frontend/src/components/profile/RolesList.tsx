import type { components } from '../../api/schema';
import { useEditableList } from '../../hooks/useEditableList';

type PastRole = components['schemas']['PastRole'];

interface RoleError {
  title: boolean;
  company: boolean;
}

interface RolesListProps {
  roles: PastRole[];
  errors: RoleError[];
  onChange: (next: PastRole[]) => void;
}

const emptyRole = (): PastRole => ({
  title: '',
  company: '',
  start_date: null,
  end_date: null,
  description: null,
});

export function RolesList({ roles, errors, onChange }: RolesListProps) {
  const {
    updateEntry: updateRole,
    removeEntry: removeRole,
    addEntry: addRole,
  } = useEditableList(roles, onChange, emptyRole);

  return (
    <div className="card p-4">
      <h2 className="mb-3 text-lg font-semibold">Past roles</h2>
      <div className="flex flex-col gap-3">
        {roles.map((role, index) => {
          const error = errors[index] ?? { title: false, company: false };
          return (
            <div
              key={index}
              className="flex flex-col gap-2 border-b border-[var(--color-border)] pb-3 last:border-0"
            >
              <div className="flex flex-wrap gap-2">
                <input
                  className={`input flex-1 ${error.title ? 'border-[var(--color-danger)]' : ''}`}
                  aria-label={`Role ${index + 1} title`}
                  placeholder="Title"
                  value={role.title}
                  onChange={(e) => updateRole(index, { ...role, title: e.target.value })}
                />
                <input
                  className={`input flex-1 ${error.company ? 'border-[var(--color-danger)]' : ''}`}
                  aria-label={`Role ${index + 1} company`}
                  placeholder="Company"
                  value={role.company}
                  onChange={(e) => updateRole(index, { ...role, company: e.target.value })}
                />
              </div>
              <div className="flex flex-wrap gap-2">
                <input
                  className="input flex-1"
                  aria-label={`Role ${index + 1} start date`}
                  placeholder="Start date"
                  value={role.start_date ?? ''}
                  onChange={(e) =>
                    updateRole(index, { ...role, start_date: e.target.value || null })
                  }
                />
                <input
                  className="input flex-1"
                  aria-label={`Role ${index + 1} end date`}
                  placeholder="End date"
                  value={role.end_date ?? ''}
                  onChange={(e) => updateRole(index, { ...role, end_date: e.target.value || null })}
                />
              </div>
              <textarea
                className="input"
                aria-label={`Role ${index + 1} description`}
                placeholder="Description"
                value={role.description ?? ''}
                onChange={(e) =>
                  updateRole(index, { ...role, description: e.target.value || null })
                }
              />
              <button
                type="button"
                className="self-start text-xs text-[var(--color-danger)]"
                onClick={() => removeRole(index)}
              >
                Remove
              </button>
            </div>
          );
        })}
      </div>
      <button type="button" className="btn btn-primary mt-3" onClick={addRole}>
        Add role
      </button>
    </div>
  );
}
