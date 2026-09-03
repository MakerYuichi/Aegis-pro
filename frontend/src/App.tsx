import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { ThemeProvider } from './components/ThemeProvider';
import { Dashboard } from './pages/Dashboard';
import { IncidentDetail } from './pages/IncidentDetail';
import { ApprovalDashboard } from './pages/ApprovalDashboard';
import { IncidentsPage } from './pages/IncidentsPage';
import { ServicesPage } from './pages/ServicesPage';
import { OnCallPage } from './pages/OnCallPage';
import { Settings } from './pages/Settings';
import { Navbar } from './components/Navbar';

function App() {
  return (
    <ThemeProvider defaultTheme="light">
      <BrowserRouter>
        <div className="min-h-screen bg-light-bg dark:bg-dark-bg transition-colors">
          <Navbar />
          <main className="container mx-auto px-4 py-8">
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/incident/:id" element={<IncidentDetail />} />
              <Route path="/incidents" element={<IncidentsPage />} />
              <Route path="/services" element={<ServicesPage />} />
              <Route path="/oncall" element={<OnCallPage />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="/approvals" element={<ApprovalDashboard />} />
            </Routes>
          </main>
        </div>
      </BrowserRouter>
    </ThemeProvider>
  );
}

export default App;
