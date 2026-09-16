import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { useAuth0 } from '@auth0/auth0-react';
import { ThemeProvider } from './components/ThemeProvider';
import { Dashboard } from './pages/Dashboard';
import { IncidentDetail } from './pages/IncidentDetail';
import { ApprovalDashboard } from './pages/ApprovalDashboard';
import { IncidentsPage } from './pages/IncidentsPage';
import { ServicesPage } from './pages/ServicesPage';
import { OnCallPage } from './pages/OnCallPage';
import { Settings } from './pages/Settings';
import { Navbar } from './components/Navbar';
import { LoginGate } from './components/LoginGate';

function App() {
  const { isLoading, isAuthenticated, error } = useAuth0();

  // Show a loading screen while Auth0 initializes
  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-light-bg dark:bg-dark-bg">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500 mx-auto mb-4" />
          <p className="text-gray-500">Initializing AEGIS PRO...</p>
        </div>
      </div>
    );
  }

  // If not authenticated, show login screen instead of the app
  if (!isAuthenticated) {
    return (
      <ThemeProvider defaultTheme="light">
        <LoginGate error={error} />
      </ThemeProvider>
    );
  }

  // Authenticated: render the normal app
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