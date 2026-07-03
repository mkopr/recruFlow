import { BrowserRouter, Route, Routes } from 'react-router-dom';

import { OfferListPage } from './pages/OfferListPage';

function App() {
  return (
    <div className="min-h-screen bg-[var(--color-bg)] text-[var(--color-text)]">
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<OfferListPage />} />
        </Routes>
      </BrowserRouter>
    </div>
  );
}

export default App;
