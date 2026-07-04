import { BrowserRouter, Link, Route, Routes } from 'react-router-dom';

import { OfferListPage } from './pages/OfferListPage';
import { ProfileEditorPage } from './pages/ProfileEditorPage';

function App() {
  return (
    <div className="min-h-screen bg-[var(--color-bg)] text-[var(--color-text)]">
      <BrowserRouter>
        <nav className="flex gap-4 border-b border-[var(--color-border)] px-[var(--spacing-page)] py-3 text-sm">
          <Link to="/" className="text-[var(--color-accent)] hover:underline">
            Offers
          </Link>
          <Link to="/profile" className="text-[var(--color-accent)] hover:underline">
            Profile
          </Link>
        </nav>
        <Routes>
          <Route path="/" element={<OfferListPage />} />
          <Route path="/profile" element={<ProfileEditorPage />} />
        </Routes>
      </BrowserRouter>
    </div>
  );
}

export default App;
