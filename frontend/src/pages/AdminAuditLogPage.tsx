/**
 * AdminAuditLogPage — a merged chronological timeline of what happened.
 *
 * Today this merges two existing sources:
 *   - demo_sessions rows (from /admin/demo-sessions)
 *   - alert_history rows (from /api/v1/oncall/alert/history)
 *
 * When the `audit_log` table lands (see issue #<audit-issue>), this
 * page reads from GET /admin/audit-log instead.
 *
 * Route: /admin/audit-log
 */
import { useEffect, useState } from 'react';
import {
  RefreshCw, Activity, Bell, AlertTriangle, CheckCircle, XCircle,
  Clock,
} from 'lucide-react';
import { motion } from 'framer-motion';
import {
  useAdminApi,
  getAlertHistory,
  type AdminDemoSession,
  type Alert,
} from '../utils/api';

type LogEntry = {
  id: string;
  timestamp: string;
  source: 'demo' | 'alert';
  actor: string;
  action: string;
  status: 'ok' | 'failed' | 'neutral';
  detail?: string;
};

export function AdminAuditLogPage() {
  const adminApi = useAdminApi();
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sourceFilter, setSourceFilter] = useState<'all' | 'demo' | 'alert'>('all');

  const load = async () => {
    try {
      setLoading(true);
      setError(null);
      const [sessions, alertHistory] = await Promise.all([
        adminApi.fetchSessions(200),
        getAlertHistory(50),
      ]);

      const demoEntries: LogEntry[] = sessions.sessions.map((s: AdminDemoSession) => ({
        id: `demo-${s.id}`,
        timestamp: s.created_at ?? '',
        source: 'demo',
        actor: s.parsed_org ? `${s.parsed_org}/${s.parsed_repo ?? '?'}` : 'unknown',
        action: s.parse_ok ? 'Demo analysis succeeded' : 'Demo analysis failed',
        status: s.parse_ok ? 'ok' : 'failed',
        detail: s.parse_ok
          ? (s.raw_input ?? undefined)
          : (s.error_reason ?? undefined),
      }));

      const alertEntries: LogEntry[] = (alertHistory.alerts ?? []).map((a: Alert) => ({
        id: `alert-${a.id}`,
        timestamp: a.timestamp,
        source: 'alert',
        actor: a.engineer,
        action: `Paged on ${a.service}`,
        status: a.status === 'sent' ? 'ok' : 'failed',
        detail: a.message.slice(0, 120),
      }));

      // Merge and sort newest first.
      const merged = [...demoEntries, ...alertEntries].sort(
        (a, b) => (b.timestamp || '').localeCompare(a.timestamp || '')
      );

      setEntries(merged);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load audit log');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filtered = entries.filter((e) =>
    sourceFilter === 'all' ? true : e.source === sourceFilter
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <RefreshCw className="w-7 h-7 text-brand-primary animate-spin mx-auto" />
          <p className="mt-3 text-sm text-light-muted dark:text-dark-muted">
            Loading audit log…
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
            Audit Log
          </h1>
          <p className="text-sm text-light-muted dark:text-dark-muted mt-0.5">
            {filtered.length} event{filtered.length !== 1 ? 's' : ''}
            <span className="ml-2 text-light-muted dark:text-dark-muted">
              · merged from demo sessions and alert history
            </span>
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={sourceFilter}
            onChange={(e) => setSourceFilter(e.target.value as 'all' | 'demo' | 'alert')}
            className="px-3 py-2 text-sm bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text focus:outline-none"
          >
            <option value="all">All sources</option>
            <option value="demo">Demo only</option>
            <option value="alert">Alerts only</option>
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

      {/* Entries */}
      {filtered.length === 0 ? (
        <div className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border p-14 text-center">
          <Activity className="w-14 h-14 text-light-muted dark:text-dark-muted mx-auto mb-4" />
          <h3 className="text-lg font-semibold text-light-text dark:text-dark-text mb-1">
            No events
          </h3>
          <p className="text-sm text-light-muted dark:text-dark-muted">
            {entries.length === 0
              ? 'No demo sessions or alerts recorded yet.'
              : 'No events match the current filter.'}
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {filtered.map((entry, idx) => {
            const SourceIcon = entry.source === 'demo' ? Activity : Bell;
            const StatusIcon =
              entry.status === 'ok' ? CheckCircle :
              entry.status === 'failed' ? XCircle : AlertTriangle;
            const statusColor =
              entry.status === 'ok' ? 'text-brand-success' :
              entry.status === 'failed' ? 'text-severity-critical' :
              'text-brand-warning';

            return (
              <motion.div
                key={entry.id}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: Math.min(idx * 0.01, 0.2) }}
                className="bg-light-card dark:bg-dark-card rounded-xl border border-light-border dark:border-dark-border p-4"
              >
                <div className="flex items-start gap-3">
                  <div className="flex-shrink-0 mt-0.5 flex items-center gap-1.5">
                    <StatusIcon className={`w-4 h-4 ${statusColor}`} />
                    <SourceIcon className="w-3.5 h-3.5 text-light-muted dark:text-dark-muted" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-medium text-light-text dark:text-dark-text">
                        {entry.action}
                      </span>
                      <span className="text-xs font-mono text-light-muted dark:text-dark-muted">
                        {entry.actor}
                      </span>
                    </div>
                    {entry.detail && (
                      <p className="text-xs text-light-muted dark:text-dark-muted font-mono mt-1 truncate">
                        {entry.detail}
                      </p>
                    )}
                  </div>
                  <span className="text-xs text-light-muted dark:text-dark-muted flex items-center gap-1 flex-shrink-0">
                    <Clock className="w-3 h-3" />
                    {entry.timestamp
                      ? new Date(entry.timestamp).toLocaleString()
                      : '—'}
                  </span>
                </div>
              </motion.div>
            );
          })}
        </div>
      )}
    </div>
  );
}