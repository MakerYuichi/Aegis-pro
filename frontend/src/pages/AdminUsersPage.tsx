/**
 * AdminUsersPage — users seen by the system.
 *
 * Today this reads from data we already have:
 *   - orgs that tried the demo (from /admin/demo-stats → top_orgs)
 *   - engineers who were paged (from /api/v1/oncall/alert/history)
 *
 * When the `users` table lands (see issue #86), this page
 * reads from GET /admin/users instead.
 *
 * Route: /admin/users
 */
import { useEffect, useState } from 'react';
import {
  RefreshCw, Building2, Users as UsersIcon, Clock, Bell,
} from 'lucide-react';
import { motion } from 'framer-motion';
import {
  useAdminApi,
  getAlertHistory,
  type AdminDemoStats,
  type Alert,
} from '../utils/api';

export function AdminUsersPage() {
  const adminApi = useAdminApi();
  const [stats, setStats] = useState<AdminDemoStats | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      setLoading(true);
      setError(null);
      const [statsData, alertData] = await Promise.all([
        adminApi.fetchStats(30),
        getAlertHistory(50),
      ]);
      setStats(statsData);
      setAlerts(alertData.alerts);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Distinct engineers from alert history (deduped by name).
  const engineers = Array.from(
    new Map(alerts.map((a) => [a.engineer, a])).values()
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <RefreshCw className="w-7 h-7 text-brand-primary animate-spin mx-auto" />
          <p className="mt-3 text-sm text-light-muted dark:text-dark-muted">
            Loading users…
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-light-text dark:text-dark-text">
            Users
          </h1>
          <p className="text-sm text-light-muted dark:text-dark-muted mt-0.5">
            Derived from existing data. A first-class users table is tracked as a
            follow-up.
          </p>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-2 px-4 py-2 bg-brand-primary text-white text-sm font-semibold rounded-lg hover:bg-brand-primary/90 transition"
        >
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
      </div>

      {error && (
        <div className="bg-severity-critical/10 border border-severity-critical/30 rounded-xl p-4 text-sm text-severity-critical">
          {error}
        </div>
      )}

      {/* Orgs that tried the demo */}
      <Section
        icon={Building2}
        title="Orgs that tried the demo"
        subtitle={`Top ${stats?.top_orgs.length ?? 0} in the last 30 days`}
      >
        {!stats || stats.top_orgs.length === 0 ? (
          <EmptyRow text="No demo activity yet." />
        ) : (
          <div className="divide-y divide-light-border dark:divide-dark-border">
            {stats.top_orgs.map((o) => (
              <div
                key={o.org}
                className="flex items-center justify-between py-2"
              >
                <span className="text-sm font-mono text-light-text dark:text-dark-text">
                  {o.org}
                </span>
                <span className="text-xs text-light-muted dark:text-dark-muted">
                  {o.count} {o.count === 1 ? 'session' : 'sessions'}
                </span>
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* Engineers paged */}
      <Section
        icon={Bell}
        title="Engineers paged"
        subtitle={`From the last ${alerts.length} alerts`}
      >
        {engineers.length === 0 ? (
          <EmptyRow text="No alerts recorded yet." />
        ) : (
          <div className="divide-y divide-light-border dark:divide-dark-border">
            {engineers.map((a) => (
              <div
                key={a.engineer}
                className="flex items-center justify-between py-2"
              >
                <div className="flex items-center gap-2">
                  <UsersIcon className="w-3.5 h-3.5 text-brand-primary" />
                  <span className="text-sm font-mono text-light-text dark:text-dark-text">
                    {a.engineer}
                  </span>
                </div>
                <div className="flex items-center gap-2 text-xs text-light-muted dark:text-dark-muted">
                  <Clock className="w-3 h-3" />
                  {a.timestamp ? new Date(a.timestamp).toLocaleString() : '—'}
                </div>
              </div>
            ))}
          </div>
        )}
      </Section>
    </div>
  );
}

function Section({
  icon: Icon,
  title,
  subtitle,
  children,
}: {
  icon: typeof Building2;
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border p-5"
    >
      <div className="flex items-center gap-2 mb-1">
        <Icon className="w-4 h-4 text-brand-primary" />
        <h2 className="text-sm font-bold text-light-text dark:text-dark-text">
          {title}
        </h2>
      </div>
      <p className="text-xs text-light-muted dark:text-dark-muted mb-4">
        {subtitle}
      </p>
      {children}
    </motion.div>
  );
}

function EmptyRow({ text }: { text: string }) {
  return (
    <p className="text-sm text-light-muted dark:text-dark-muted py-2">
      {text}
    </p>
  );
}
