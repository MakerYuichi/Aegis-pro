/**
 * AdminHomePage — the admin hub.
 *
 * Shows live demo stats for the trailing 7 days plus a grid of cards
 * linking to each admin tool. The stats come from the same endpoint
 * DemoStatsPage uses.
 *
 * Route: /admin
 */
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Activity, BarChart3, AlertTriangle, Building2, ArrowRight,
  RefreshCw, Users, FileText, Sliders,
} from 'lucide-react';
import { motion } from 'framer-motion';
import { useAdminApi, type AdminDemoStats } from '../utils/api';

type ToolCard = {
  path: string;
  title: string;
  description: string;
  icon: typeof Activity;
  section: 'demo' | 'users' | 'audit';
};

const TOOLS: ToolCard[] = [
  {
    path: '/admin/demo',
    title: 'Demo Config',
    description: 'Read-only view of the sample incident, rate limits, and try cap. Reset your demo session here.',
    icon: Sliders,
    section: 'demo',
  },
  {
    path: '/admin/demo-activity',
    title: 'Demo Activity',
    description: 'Every /demo/generate call, newest first. See which orgs are trying the demo and which URLs fail to parse.',
    icon: Activity,
    section: 'demo',
  },
  {
    path: '/admin/demo-stats',
    title: 'Demo Stats',
    description: 'Aggregates over a trailing window — sessions by day, top orgs, parse failure breakdown.',
    icon: BarChart3,
    section: 'demo',
  },
  {
    path: '/admin/users',
    title: 'Users',
    description: 'Orgs that tried the demo and engineers paged recently. Derived from existing data.',
    icon: Users,
    section: 'users',
  },
  {
    path: '/admin/audit-log',
    title: 'Audit Log',
    description: 'Merged chronological timeline of demo sessions and alert history.',
    icon: FileText,
    section: 'audit',
  },
];

export function AdminHomePage() {
  const adminApi = useAdminApi();
  const [stats, setStats] = useState<AdminDemoStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await adminApi.fetchStats(7);
      setStats(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load stats');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const topOrg = stats?.top_orgs[0]?.org ?? '—';

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-light-text dark:text-dark-text">
            Admin Panel
          </h1>
          <p className="text-sm text-light-muted dark:text-dark-muted mt-0.5">
            Demo analytics for the trailing 7 days.
          </p>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-2 px-3 py-1.5 text-sm text-light-muted dark:text-dark-muted hover:text-brand-primary transition"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          Refresh
        </button>
      </div>

      {error && (
        <div className="bg-severity-critical/10 border border-severity-critical/30 rounded-xl p-4 text-sm text-severity-critical">
          {error}
        </div>
      )}

      {/* Live stat cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          icon={Activity}
          label="Sessions (7d)"
          value={loading ? '—' : String(stats?.total_sessions ?? 0)}
          tint="brand"
        />
        <StatCard
          icon={AlertTriangle}
          label="Parse failures (7d)"
          value={loading ? '—' : String(stats?.parse_failures.total ?? 0)}
          tint="critical"
        />
        <StatCard
          icon={Building2}
          label="Distinct orgs (7d)"
          value={loading ? '—' : String(stats?.top_orgs.length ?? 0)}
          tint="success"
        />
        <StatCard
          icon={Users}
          label="Top org (7d)"
          value={loading ? '—' : topOrg}
          tint="brand"
          mono
        />
      </div>

      {/* Tool cards */}
      <div>
        <h2 className="text-sm font-semibold uppercase tracking-wider text-light-muted dark:text-dark-muted mb-3">
          Tools
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {TOOLS.map((tool, idx) => {
            const Icon = tool.icon;
            return (
              <motion.div
                key={tool.path}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: idx * 0.04 }}
              >
                <Link
                  to={tool.path}
                  className="group block h-full bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border p-5 hover:border-brand-primary/50 transition"
                >
                  <div className="flex items-start gap-3 mb-3">
                    <div className="p-2 rounded-lg bg-brand-primary/10 text-brand-primary border border-brand-primary/20">
                      <Icon className="w-4 h-4" />
                    </div>
                    <h3 className="text-base font-semibold text-light-text dark:text-dark-text flex-1">
                      {tool.title}
                    </h3>
                    <ArrowRight className="w-4 h-4 text-light-muted dark:text-dark-muted group-hover:text-brand-primary group-hover:translate-x-0.5 transition" />
                  </div>
                  <p className="text-sm text-light-muted dark:text-dark-muted leading-relaxed">
                    {tool.description}
                  </p>
                </Link>
              </motion.div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  tint,
  mono = false,
}: {
  icon: typeof Activity;
  label: string;
  value: string;
  tint: 'brand' | 'critical' | 'success';
  mono?: boolean;
}) {
  const tintClass = {
    brand:    'text-brand-primary     bg-brand-primary/10     border-brand-primary/20',
    critical: 'text-severity-critical bg-severity-critical/10 border-severity-critical/20',
    success:  'text-brand-success     bg-brand-success/10     border-brand-success/20',
  }[tint];

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border p-5"
    >
      <div className="flex items-center gap-3 mb-3">
        <div className={`p-2 rounded-lg border ${tintClass}`}>
          <Icon className="w-4 h-4" />
        </div>
        <span className="text-xs font-semibold uppercase tracking-wide text-light-muted dark:text-dark-muted">
          {label}
        </span>
      </div>
      <p
        className={`font-bold text-light-text dark:text-dark-text ${
          mono ? 'text-xl font-mono truncate' : 'text-3xl'
        }`}
      >
        {value}
      </p>
    </motion.div>
  );
}
