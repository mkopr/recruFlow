import { BrowserRouter, Link, Route, Routes } from 'react-router-dom';

import { OfferListPage } from './pages/OfferListPage';
import { ProfileEditorPage } from './pages/ProfileEditorPage';
import { SettingsPage } from './pages/SettingsPage';

function App() {
  return (
    <div className="min-h-screen bg-[var(--color-bg)] text-[var(--color-text)]">
      <BrowserRouter>
        <nav className="flex gap-4 border-b border-[var(--color-border)] px-4 py-3 text-sm sm:px-6 lg:px-8">
          <Link to="/" className="text-[var(--color-accent)] hover:underline">
            Offers
          </Link>
          <Link to="/profile" className="text-[var(--color-accent)] hover:underline">
            Profile
          </Link>
          <Link to="/settings" className="text-[var(--color-accent)] hover:underline">
            Settings
          </Link>
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
