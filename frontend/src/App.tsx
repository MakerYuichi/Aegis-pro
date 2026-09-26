import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
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
import { DemoPage } from './pages/DemoPage';
import { AdminHomePage } from './pages/AdminHomePage';
import { AdminDemoPage } from './pages/AdminDemoPage';
import { DemoActivityPage } from './pages/DemoActivityPage';
import { DemoStatsPage } from './pages/DemoStatsPage';
import { SessionReplayPage } from './pages/SessionReplayPage';
import { AdminUsersPage } from './pages/AdminUsersPage';
import { AdminAuditLogPage } from './pages/AdminAuditLogPage';
import { OnboardingPage } from './pages/OnboardingPage';
import { AdminLayout } from './components/AdminLayout';
import { useIsAdmin } from './hooks/useIsAdmin';
import type { ReactNode } from 'react';

function LoadingScreen() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-light-bg dark:bg-dark-bg">
      <div className="text-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500 mx-auto mb-4" />
        <p className="text-gray-500">Initializing AEGIS PRO...</p>
      </div>
    </div>
  );
}

function RequireAuth({
  isAuthenticated,
  error,
  children,
}: {
  isAuthenticated: boolean;
  error: Error | null | undefined;
  children: ReactNode;
}) {
  if (!isAuthenticated) {
    return <LoginGate error={error ?? undefined} />;
  }
  return (
    <div className="min-h-screen bg-light-bg dark:bg-dark-bg transition-colors">
      <Navbar />
      <main className="container mx-auto px-4 py-8">{children}</main>
    </div>
  );
}

/**
 * Admin shell (Option C). No dashboard Navbar. AdminLayout provides
 * its own top bar and sub-navigation.
 */
function RequireAdmin({
  isAuthenticated,
  error,
  children,
}: {
  isAuthenticated: boolean;
  error: Error | null | undefined;
  children: ReactNode;
}) {
  const { isAdmin, loading } = useIsAdmin();

  if (!isAuthenticated) {
    return <LoginGate error={error ?? undefined} />;
  }
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-light-bg dark:bg-dark-bg">
        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-brand-primary" />
      </div>
    );
  }
  if (!isAdmin) {
    return <Navigate to="/" replace />;
  }
  return (
    <div className="min-h-screen bg-light-bg dark:bg-dark-bg transition-colors">
      <main className="container mx-auto px-4 py-6">
        <AdminLayout>{children}</AdminLayout>
      </main>
    </div>
  );
}

function App() {
  const { isLoading, isAuthenticated, error } = useAuth0();

  if (isLoading) {
    return <LoadingScreen />;
  }

  return (
    <ThemeProvider defaultTheme="light">
      <BrowserRouter>
        <Routes>
          {/* Public demo */}
          <Route path="/demo" element={<DemoPage />} />

          {/* `/` is the demo when signed out, the Dashboard when signed in. */}
          <Route
            path="/"
            element={
              isAuthenticated ? (
                <RequireAuth isAuthenticated={isAuthenticated} error={error}>
                  <Dashboard />
                </RequireAuth>
              ) : (
                <DemoPage />
              )
            }
          />

          {/* Authenticated dashboard routes */}
          <Route path="/incident/:id" element={<RequireAuth isAuthenticated={isAuthenticated} error={error}><IncidentDetail /></RequireAuth>} />
          <Route path="/incidents"    element={<RequireAuth isAuthenticated={isAuthenticated} error={error}><IncidentsPage /></RequireAuth>} />
          <Route path="/services"     element={<RequireAuth isAuthenticated={isAuthenticated} error={error}><ServicesPage /></RequireAuth>} />
          <Route path="/oncall"       element={<RequireAuth isAuthenticated={isAuthenticated} error={error}><OnCallPage /></RequireAuth>} />
          <Route path="/settings"     element={<RequireAuth isAuthenticated={isAuthenticated} error={error}><Settings /></RequireAuth>} />
          <Route path="/approvals"    element={<RequireAuth isAuthenticated={isAuthenticated} error={error}><ApprovalDashboard /></RequireAuth>} />
          <Route path="/onboarding"  element={<RequireAuth isAuthenticated={isAuthenticated} error={error}><OnboardingPage /></RequireAuth>} />

          {/* Admin shell (Option C) */}
          <Route path="/admin"                    element={<RequireAdmin isAuthenticated={isAuthenticated} error={error}><AdminHomePage /></RequireAdmin>} />
          <Route path="/admin/demo"               element={<RequireAdmin isAuthenticated={isAuthenticated} error={error}><AdminDemoPage /></RequireAdmin>} />
          <Route path="/admin/demo-activity"      element={<RequireAdmin isAuthenticated={isAuthenticated} error={error}><DemoActivityPage /></RequireAdmin>} />
          <Route path="/admin/demo-stats"         element={<RequireAdmin isAuthenticated={isAuthenticated} error={error}><DemoStatsPage /></RequireAdmin>} />
          <Route path="/admin/demo-sessions/:id"  element={<RequireAdmin isAuthenticated={isAuthenticated} error={error}><SessionReplayPage /></RequireAdmin>} />
          <Route path="/admin/users"              element={<RequireAdmin isAuthenticated={isAuthenticated} error={error}><AdminUsersPage /></RequireAdmin>} />
          <Route path="/admin/audit-log"          element={<RequireAdmin isAuthenticated={isAuthenticated} error={error}><AdminAuditLogPage /></RequireAdmin>} />

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </ThemeProvider>
  );
}

export default App;
