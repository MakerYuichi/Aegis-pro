/**
 * DemoStatsPage — aggregate demo activity over a trailing window.
 *
 * The parse-failure breakdown is the product signal: if unsupported_host
 * dominates, add support for that host. If a specific org shows up a lot,
 * that's a lead worth a call.
 *
 * Route: /admin/demo-stats
 */
import { useEffect, useState } from 'react';
import {
  RefreshCw, Activity, Building2, AlertTriangle, BarChart3,
} from 'lucide-react';
import { motion } from 'framer-motion';
import { useAdminApi, type AdminDemoStats } from '../utils/api';

export function DemoStatsPage() {
  const adminApi = useAdminApi();
  const [stats, setStats] = useState<AdminDemoStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [days, setDays] = useState(30);

  const load = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await adminApi.fetchStats(days);
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
  }, [days]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <RefreshCw className="w-7 h-7 text-brand-primary animate-spin mx-auto" />
          <p className="mt-3 text-sm text-light-muted dark:text-dark-muted">
            Loading stats…
          </p>
        </div>
      </div>
    );
  }

  if (!stats) {
    return (
      <div className="bg-severity-critical/10 border border-severity-critical/30 rounded-xl p-4 text-sm text-severity-critical">
        {error ?? 'No stats available.'}
      </div>
    );
  }

  const maxDayCount = Math.max(1, ...stats.sessions_by_day.map((d) => d.count));

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-light-text dark:text-dark-text">
            Demo Stats
          </h1>
          <p className="text-sm text-light-muted dark:text-dark-muted mt-0.5">
            Trailing {stats.window_days}-day window
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="px-3 py-2 text-sm bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text focus:outline-none"
          >
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
            <option value={365}>Last 365 days</option>
          </select>
          <button
            onClick={load}
            className="flex items-center gap-2 px-4 py-2 bg-brand-primary text-white text-sm font-semibold rounded-lg hover:bg-brand-primary/90 transition"
          >
            <RefreshCw className="w-4 h-4" />
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-severity-critical/10 border border-severity-critical/30 rounded-xl p-4 text-sm text-severity-critical">
          {error}
        </div>
      )}

      {/* Top-line stats */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard
          icon={Activity}
          label="Total sessions"
          value={stats.total_sessions}
          tint="brand"
        />
        <StatCard
          icon={AlertTriangle}
          label="Parse failures"
          value={stats.parse_failures.total}
          tint="critical"
        />
        <StatCard
          icon={Building2}
          label="Distinct orgs"
          value={stats.top_orgs.length}
          tint="success"
        />
      </div>

      {/* Sessions by day */}
      <Section title="Sessions by day" icon={BarChart3}>
        {stats.sessions_by_day.length === 0 ? (
          <EmptyRow text="No sessions in this window." />
        ) : (
          <div className="space-y-1.5">
            {stats.sessions_by_day.map((d) => (
              <div key={d.date} className="flex items-center gap-3">
                <span className="w-24 text-xs text-light-muted dark:text-dark-muted font-mono flex-shrink-0">
                  {d.date}
                </span>
                <div className="flex-1 bg-light-surface dark:bg-dark-surface rounded-full h-3 overflow-hidden">
                  <div
                    className="h-full bg-brand-primary rounded-full transition-all"
                    style={{ width: `${(d.count / maxDayCount) * 100}%` }}
                  />
                </div>
                <span className="w-10 text-right text-xs font-semibold text-light-text dark:text-dark-text">
                  {d.count}
                </span>
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* Top orgs */}
      <Section title="Top orgs pasted" icon={Building2}>
        {stats.top_orgs.length === 0 ? (
          <EmptyRow text="No orgs pasted yet." />
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
                <span className="text-sm font-semibold text-brand-primary">
                  {o.count}
                </span>
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* Parse failures */}
      <Section title="Parse failures by reason" icon={AlertTriangle}>
        {stats.parse_failures.by_reason.length === 0 ? (
          <EmptyRow text="No parse failures in this window." />
        ) : (
          <div className="divide-y divide-light-border dark:divide-dark-border">
            {stats.parse_failures.by_reason.map((f) => (
              <div
                key={f.reason}
                className="flex items-center justify-between py-2"
              >
                <span className="text-sm font-mono text-severity-critical">
                  {f.reason}
                </span>
                <span className="text-sm font-semibold text-light-text dark:text-dark-text">
                  {f.count}
                </span>
              </div>
            ))}
          </div>
        )}
      </Section>
    </div>
  );
}

// ── Small presentational bits ────────────────────────────────────────────

function StatCard({
  icon: Icon,
  label,
  value,
  tint,
}: {
  icon: typeof Activity;
  label: string;
  value: number;
  tint: 'brand' | 'critical' | 'success';
}) {
  const tintClass = {
    brand: 'text-brand-primary bg-brand-primary/10 border-brand-primary/20',
    critical: 'text-severity-critical bg-severity-critical/10 border-severity-critical/20',
    success: 'text-brand-success bg-brand-success/10 border-brand-success/20',
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
      <p className="text-3xl font-bold text-light-text dark:text-dark-text">
        {value}
      </p>
    </motion.div>
  );
}

function Section({
  title,
  icon: Icon,
  children,
}: {
  title: string;
  icon: typeof Activity;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border p-5">
      <div className="flex items-center gap-2 mb-4">
        <Icon className="w-4 h-4 text-brand-primary" />
        <h2 className="text-sm font-bold text-light-text dark:text-dark-text">
          {title}
        </h2>
      </div>
      {children}
    </div>
  );
}

function EmptyRow({ text }: { text: string }) {
  return (
    <p className="text-sm text-light-muted dark:text-dark-muted py-2">
      {text}
    </p>
  );
}
