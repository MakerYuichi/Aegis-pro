/**
 * AdminLayout — the Option C admin shell.
 *
 * The admin panel is a distinct section: it does NOT render the
 * dashboard Navbar. This layout provides its own top bar with the
 * wordmark (links to /admin), theme toggle, user info, logout,
 * "Preview Demo", and "Back to Dashboard". Below the top bar is the
 * AdminTabs sub-navigation, then the page content.
 */
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import {
  Shield, ArrowLeft, ExternalLink, Moon, Sun, LogOut,
} from 'lucide-react';
import { useAuth0 } from '@auth0/auth0-react';
import { useTheme } from './ThemeProvider';
import { AdminTabs } from './AdminTabs';

export function AdminLayout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth0();
  const { theme, toggleTheme } = useTheme();

  const handleLogout = () =>
    logout({ logoutParams: { returnTo: window.location.origin } });

  return (
    <div className="space-y-4">
      {/* ── Admin top bar ─────────────────────────────────────────── */}
      <div className="flex items-center justify-between gap-3 pb-3 border-b border-light-border dark:border-dark-border flex-wrap">
        {/* Wordmark — links to the admin hub */}
        <Link to="/admin" className="flex items-center gap-2 group">
          <Shield className="w-7 h-7 text-brand-primary" />
          <span className="text-lg font-bold text-light-text dark:text-dark-text">
            AEGIS PRO
          </span>
          <span className="text-[10px] uppercase tracking-widest bg-brand-primary/10 text-brand-primary px-2 py-0.5 rounded-full font-semibold">
            Admin
          </span>
        </Link>

        {/* Right side controls */}
        <div className="flex items-center gap-2">
          {/* Preview Demo — opens /demo in a new tab */}
          <a
            href="/demo"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-light-muted dark:text-dark-muted hover:text-brand-primary border border-light-border dark:border-dark-border rounded-lg transition"
          >
            Preview Demo
            <ExternalLink className="w-3 h-3" />
          </a>

          {/* Back to Dashboard */}
          <Link
            to="/"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-light-muted dark:text-dark-muted hover:text-brand-primary border border-light-border dark:border-dark-border rounded-lg transition"
          >
            <ArrowLeft className="w-3 h-3" />
            Back to Dashboard
          </Link>

          {/* Theme toggle */}
          <button
            onClick={toggleTheme}
            className="p-2 rounded-lg bg-light-surface dark:bg-dark-surface hover:bg-light-border dark:hover:bg-dark-border text-light-text dark:text-dark-text transition border border-light-border dark:border-dark-border"
            aria-label="Toggle theme"
          >
            {theme === 'dark' ? (
              <Sun className="w-4 h-4 text-brand-warning" />
            ) : (
              <Moon className="w-4 h-4 text-brand-primary" />
            )}
          </button>

          {/* User + logout */}
          {user && (
            <div className="flex items-center gap-2 pl-2 border-l border-light-border dark:border-dark-border">
              <div className="hidden sm:flex flex-col items-end">
                <span className="text-xs font-medium text-light-text dark:text-dark-text">
                  {user.name || user.email}
                </span>
                {user.name && (
                  <span className="text-[10px] text-light-muted dark:text-dark-muted">
                    {user.email}
                  </span>
                )}
              </div>
              <button
                onClick={handleLogout}
                className="p-2 rounded-lg bg-light-surface dark:bg-dark-surface hover:bg-red-50 dark:hover:bg-red-900/20 text-light-text dark:text-dark-text hover:text-red-600 dark:hover:text-red-400 transition border border-light-border dark:border-dark-border"
                aria-label="Logout"
                title="Logout"
              >
                <LogOut className="w-4 h-4" />
              </button>
            </div>
          )}
        </div>
      </div>

      {/* ── Sub-navigation ────────────────────────────────────────── */}
      <AdminTabs />

      {/* ── Page content ──────────────────────────────────────────── */}
      <div>{children}</div>
    </div>
  );
}
