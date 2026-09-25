/**
 * AdminTabs — sub-navigation across the admin section.
 *
 * Structure (left to right):
 *   Demo Config  ·  Activity  Stats  |  Users  Audit Log
 *
 * "Demo Config" is a section header that links to /admin/demo. Activity
 * and Stats are sub-pages of the Demo section, visually indented under
 * it. Users and Audit Log are top-level sections.
 *
 * The active-tab logic uses prefix matching so sub-routes (like
 * /admin/demo-sessions/:id) keep their parent tab highlighted.
 */
import { Link, useLocation } from 'react-router-dom';
import {
  Sliders, Activity, BarChart3, Users, FileText,
} from 'lucide-react';

type Tab = {
  path: string;
  label: string;
  icon: typeof Activity;
  /** If set, the tab is active for any path starting with this prefix. */
  matchPrefix?: string;
  /** Visually grouped under the previous section header. */
  indent?: boolean;
};

// Section: Demo
const DEMO_SECTION: Tab = {
  path: '/admin/demo',
  label: 'Demo Config',
  icon: Sliders,
  matchPrefix: '/admin/demo',
};

const DEMO_SUBTABS: Tab[] = [
  { path: '/admin/demo-activity', label: 'Activity', icon: Activity,  indent: true },
  { path: '/admin/demo-stats',    label: 'Stats',    icon: BarChart3, indent: true },
];

// Section: Users & Audit
const OTHER_TABS: Tab[] = [
  { path: '/admin/users',     label: 'Users',     icon: Users,    matchPrefix: '/admin/users' },
  { path: '/admin/audit-log', label: 'Audit Log', icon: FileText, matchPrefix: '/admin/audit' },
];

function isActive(path: string, currentPath: string): boolean {
  if (path === '/admin/demo') return currentPath === '/admin/demo';
  if (path === '/admin/demo-activity') return currentPath.startsWith('/admin/demo-sessions');
  if (path.startsWith('/admin/')) return currentPath.startsWith(path);
  return currentPath === path;
}

export function AdminTabs() {
  const location = useLocation();
  const current = location.pathname;

  const renderTab = (tab: Tab) => {
    const Icon = tab.icon;
    const active = isActive(tab.path, current);
    return (
      <Link
        key={tab.path}
        to={tab.path}
        className={`flex items-center gap-2 px-3 py-3 text-sm font-medium border-b-2 transition-colors ${
          tab.indent ? 'pl-5' : ''
        } ${
          active
            ? 'border-brand-primary text-brand-primary'
            : 'border-transparent text-light-muted dark:text-dark-muted hover:text-light-text dark:hover:text-dark-text hover:border-light-border dark:hover:border-dark-border'
        }`}
      >
        <Icon className="w-4 h-4" />
        {tab.label}
      </Link>
    );
  };

  return (
    <div className="border-b border-light-border dark:border-dark-border mb-6">
      <div className="flex items-center -mb-px">
        {/* Demo section */}
        {renderTab(DEMO_SECTION)}
        <span className="mx-1 text-light-muted dark:text-dark-muted">·</span>
        {DEMO_SUBTABS.map(renderTab)}

        {/* Separator between Demo and Users/Audit */}
        <span className="mx-3 h-4 w-px bg-light-border dark:bg-dark-border" aria-hidden />

        {/* Other sections */}
        {OTHER_TABS.map(renderTab)}
      </div>
    </div>
  );
}
