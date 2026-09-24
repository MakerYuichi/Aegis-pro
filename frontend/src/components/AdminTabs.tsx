/**
 * AdminTabs — sub-navigation across the admin section.
 *
 * Rendered by AdminLayout at the top of every /admin/* page. The "Admin"
 * tab goes to the hub; "Demo" groups the demo analytics sub-pages.
 *
 * Active-tab logic uses prefix matching so sub-routes (like
 * /admin/demo-sessions/:id) keep their parent tab highlighted.
 */
import { Link, useLocation } from 'react-router-dom';
import { LayoutDashboard, Sparkles, Activity, BarChart3 } from 'lucide-react';

type Tab = {
  path: string;
  label: string;
  icon: typeof Activity;
  /** If set, the tab is active for any path starting with this prefix. */
  matchPrefix?: string;
};

const TABS: Tab[] = [
  { path: '/admin',                  label: 'Admin',    icon: LayoutDashboard, matchPrefix: '/admin' },
  { path: '/admin/demo-activity',    label: 'Activity', icon: Activity,        matchPrefix: '/admin/demo' },
  { path: '/admin/demo-stats',       label: 'Stats',    icon: BarChart3 },
];

export function AdminTabs() {
  const location = useLocation();

  // Determine the "section" so the "Demo" grouping can highlight its
  // parent. This is a simple pass, good enough for the current shape.
  const inDemoSection = location.pathname.startsWith('/admin/demo');

  return (
    <div className="border-b border-light-border dark:border-dark-border mb-6">
      <div className="flex items-center gap-1 -mb-px">
        {TABS.map((tab) => {
          const Icon = tab.icon;
          const isActive = tab.matchPrefix
            ? location.pathname === tab.path
              ? true
              : location.pathname.startsWith(tab.matchPrefix) &&
                // "Admin" hub should only be active on the exact path.
                tab.path !== '/admin'
            : location.pathname === tab.path;

          return (
            <Link
              key={tab.path}
              to={tab.path}
              className={`flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                isActive
                  ? 'border-brand-primary text-brand-primary'
                  : 'border-transparent text-light-muted dark:text-dark-muted hover:text-light-text dark:hover:text-dark-text hover:border-light-border dark:hover:border-dark-border'
              }`}
            >
              <Icon className="w-4 h-4" />
              {tab.label}
            </Link>
          );
        })}
      </div>
      {/* Section indicator — only shows when in a demo sub-page, so the
          "Demo" grouping is explicit. */}
      {inDemoSection && (
        <div className="pb-1 -mt-px">
          <span className="text-[10px] uppercase tracking-widest text-light-muted dark:text-dark-muted">
            Demo analytics
          </span>
        </div>
      )}
    </div>
  );
}
