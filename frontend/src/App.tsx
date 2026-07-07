import { BrowserRouter, NavLink, Route, Routes } from 'react-router-dom';

import { useGradeAAlerts } from './hooks/useGradeAAlerts';
import { OfferListPage } from './pages/OfferListPage';
import { ProfileEditorPage } from './pages/ProfileEditorPage';
import { SettingsPage } from './pages/SettingsPage';

const NAV_LINKS = [
  { to: '/', label: 'Offers' },
  { to: '/profile', label: 'Profile' },
  { to: '/settings', label: 'Settings' },
];

function App() {
  useGradeAAlerts();

  return (
    <div className="min-h-screen bg-[var(--color-bg)] text-[var(--color-text)]">
      <BrowserRouter>
        <nav className="flex items-center gap-1 border-b border-[var(--color-border)] px-4 py-3 sm:px-6 lg:px-8">
          <span className="mr-3 text-sm font-semibold text-[var(--color-text-muted)]">
            recruFlow
          </span>
          {NAV_LINKS.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.to === '/'}
              className={({ isActive }) =>
                `rounded-full px-3 py-1.5 text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-[var(--color-surface)] text-[var(--color-text)]'
                    : 'text-[var(--color-text-muted)] hover:text-[var(--color-text)]'
                }`
              }
            >
              {link.label}
            </NavLink>
          ))}
        </nav>
        <Routes>
          <Route path="/" element={<OfferListPage />} />
          <Route path="/profile" element={<ProfileEditorPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </BrowserRouter>
    </div>
  );
}

export default App;
