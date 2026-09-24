/**
 * AdminLayout — the chrome around every /admin/* page.
 *
 * Renders the sub-navigation (AdminTabs) and a "Back to Dashboard"
 * button at the top, then the page content. Wrapping all admin pages
 * here means individual pages don't need to know about the tab bar or
 * the return-to-dashboard affordance.
 */
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { AdminTabs } from './AdminTabs';

export function AdminLayout({ children }: { children: ReactNode }) {
  return (
    <div className="space-y-2">
      {/* Top bar: back to dashboard + admin label */}
      <div className="flex items-center justify-between">
        <Link
          to="/"
          className="inline-flex items-center gap-1.5 text-sm text-light-muted dark:text-dark-muted hover:text-brand-primary transition"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Back to Dashboard
        </Link>
        <span className="text-xs uppercase tracking-widest text-light-muted dark:text-dark-muted font-semibold">
          Admin
        </span>
      </div>

      {/* Sub-navigation */}
      <AdminTabs />

      {/* Page content */}
      <div>{children}</div>
    </div>
  );
}
