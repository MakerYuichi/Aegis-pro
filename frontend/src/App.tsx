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
import { DemoActivityPage } from './pages/DemoActivityPage';
import { DemoStatsPage } from './pages/DemoStatsPage';
import { SessionReplayPage } from './pages/SessionReplayPage';
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

/**
 * Wraps a route that requires authentication.
 *
 * When signed out, renders the LoginGate instead of the protected page.
 * When signed in, renders the standard authenticated shell — Navbar plus
 * a main container. The demo routes (`/` when signed out, `/demo` always)
 * do NOT use this wrapper and therefore render without a Navbar.
 */
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
 * Wraps a route that requires admin access.
 *
 * Composes RequireAuth (renders LoginGate if signed out) with an
 * is_admin check. Non-admins are redirected to `/` rather than shown
 * a 403 page — the admin panel simply doesn't exist for them.
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
      <Navbar />
      <main className="container mx-auto px-4 py-8">{children}</main>
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
          {/* ── Public demo routes ────────────────────────────────── */}

          {/* `/demo` is always the demo, even when signed in — an escape
              hatch for the operator to preview what a prospect sees. */}
          <Route path="/demo" element={<DemoPage />} />

          {/* `/` is the demo when signed out, the Dashboard when signed in.
              This is the primary landing page for prospects. */}
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

          {/* ── Authenticated routes ──────────────────────────────── */}

          <Route
            path="/incident/:id"
            element={
              <RequireAuth isAuthenticated={isAuthenticated} error={error}>
                <IncidentDetail />
              </RequireAuth>
            }
          />
          <Route
            path="/incidents"
            element={
              <RequireAuth isAuthenticated={isAuthenticated} error={error}>
                <IncidentsPage />
              </RequireAuth>
            }
          />
          <Route
            path="/services"
            element={
              <RequireAuth isAuthenticated={isAuthenticated} error={error}>
                <ServicesPage />
              </RequireAuth>
            }
          />
          <Route
            path="/oncall"
            element={
              <RequireAuth isAuthenticated={isAuthenticated} error={error}>
                <OnCallPage />
              </RequireAuth>
            }
          />
          <Route
            path="/settings"
            element={
              <RequireAuth isAuthenticated={isAuthenticated} error={error}>
                <Settings />
              </RequireAuth>
            }
          />
          <Route
            path="/approvals"
            element={
              <RequireAuth isAuthenticated={isAuthenticated} error={error}>
                <ApprovalDashboard />
              </RequireAuth>
            }
          />

          {/* ── Admin routes ──────────────────────────────────────── */}

<Route
  path="/admin/demo-activity"
  element={
    <RequireAdmin isAuthenticated={isAuthenticated} error={error}>
      <DemoActivityPage />
    </RequireAdmin>
  }
/>
<Route
  path="/admin/demo-stats"
  element={
    <RequireAdmin isAuthenticated={isAuthenticated} error={error}>
      <DemoStatsPage />
    </RequireAdmin>
  }
/>
<Route
  path="/admin/demo-sessions/:id"
  element={
    <RequireAdmin isAuthenticated={isAuthenticated} error={error}>
      <SessionReplayPage />
    </RequireAdmin>
  }
/>

          {/* Anything unknown → home. The home handler decides
              demo vs. dashboard based on auth state. */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </ThemeProvider>
  );
}

export default App;
