/**
 * DemoActivityPage — admin view of recent demo sessions.
 *
 * One row per /demo/generate or /demo/regenerate call. This is the lead
 * signal: which orgs are pasting URLs, which parses succeed, which fail
 * and why. Each row links to SessionReplayPage for the full picture.
 *
 * Route: /admin/demo-activity
 */
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  RefreshCw, Search, Filter, CheckCircle, XCircle, ExternalLink,
  Clock, Building2, AlertTriangle,
} from 'lucide-react';
import { motion } from 'framer-motion';
import {
  useAdminApi,
  type AdminDemoSession,
} from '../utils/api';

type Filter = 'all' | 'ok' | 'failed';

export function DemoActivityPage() {
  const adminApi = useAdminApi();
  const [sessions, setSessions] = useState<AdminDemoSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>('all');
  const [search, setSearch] = useState('');
  const [limit, setLimit] = useState(100);

  const load = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await adminApi.fetchSessions(limit);
      setSessions(data.sessions);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load sessions');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [limit]);

  const filtered = sessions.filter((s) => {
    if (filter === 'ok' && !s.parse_ok) return false;
    if (filter === 'failed' && s.parse_ok) return false;
    if (search) {
      const q = search.toLowerCase();
      const hay = `${s.raw_input ?? ''} ${s.parsed_org ?? ''} ${s.parsed_repo ?? ''}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  const okCount = sessions.filter((s) => s.parse_ok).length;
  const failedCount = sessions.length - okCount;

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <RefreshCw className="w-7 h-7 text-brand-primary animate-spin mx-auto" />
          <p className="mt-3 text-sm text-light-muted dark:text-dark-muted">
            Loading demo sessions…
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
            <p className="text-sm text-light-muted dark:text-dark-muted">
            {sessions.length} session{sessions.length !== 1 ? 's' : ''}
            <span className="ml-2 px-2 py-0.5 bg-brand-success/15 text-brand-success border border-brand-success/30 rounded-full text-xs font-semibold">
              {okCount} parsed
            </span>
            {failedCount > 0 && (
              <span className="ml-2 px-2 py-0.5 bg-severity-critical/15 text-severity-critical border border-severity-critical/30 rounded-full text-xs font-semibold">
                {failedCount} failed
              </span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            className="px-3 py-2 text-sm bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text focus:outline-none"
          >
            <option value={50}>Last 50</option>
            <option value={100}>Last 100</option>
            <option value={250}>Last 250</option>
            <option value={500}>Last 500</option>
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

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-light-muted dark:text-dark-muted" />
          <input
            type="text"
            placeholder="Search URL, org, or repo…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-10 pr-4 py-2 text-sm bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text focus:outline-none focus:ring-2 focus:ring-brand-primary/30"
          />
        </div>
        <div className="flex items-center gap-2">
          <Filter className="w-4 h-4 text-light-muted dark:text-dark-muted flex-shrink-0" />
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value as Filter)}
            className="px-3 py-2 text-sm bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-light-text dark:text-dark-text focus:outline-none"
          >
            <option value="all">All</option>
            <option value="ok">Parsed</option>
            <option value="failed">Failed</option>
          </select>
        </div>
      </div>

      {/* List */}
      {filtered.length === 0 ? (
        <div className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border p-14 text-center">
          <Building2 className="w-14 h-14 text-light-muted dark:text-dark-muted mx-auto mb-4" />
          <h3 className="text-lg font-semibold text-light-text dark:text-dark-text mb-1">
            No sessions to show
          </h3>
          <p className="text-sm text-light-muted dark:text-dark-muted">
            {sessions.length === 0
              ? 'No demo sessions have been logged yet.'
              : 'No sessions match the current filters.'}
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {filtered.map((s, idx) => (
            <motion.div
              key={s.id}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: Math.min(idx * 0.02, 0.3) }}
              className="bg-light-card dark:bg-dark-card rounded-xl border border-light-border dark:border-dark-border p-4 hover:border-brand-primary/40 transition"
            >
              <div className="flex items-start gap-4">
                <div className="flex-shrink-0 mt-0.5">
                  {s.parse_ok ? (
                    <CheckCircle className="w-5 h-5 text-brand-success" />
                  ) : (
                    <XCircle className="w-5 h-5 text-severity-critical" />
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap mb-1">
                    {s.parsed_org && (
                      <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-brand-primary/10 text-brand-primary border border-brand-primary/20 font-mono">
                        {s.parsed_org}/{s.parsed_repo ?? '?'}
                      </span>
                    )}
                    {s.language_inferred && (
                      <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-light-surface dark:bg-dark-surface text-light-muted dark:text-dark-muted border border-light-border dark:border-dark-border">
                        {s.language_inferred}
                      </span>
                    )}
                    {!s.parse_ok && s.error_reason && (
                      <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-severity-critical/10 text-severity-critical border border-severity-critical/25 flex items-center gap-1">
                        <AlertTriangle className="w-3 h-3" />
                        {s.error_reason}
                      </span>
                    )}
                    <span className="text-xs text-light-muted dark:text-dark-muted flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      {s.created_at
                        ? new Date(s.created_at).toLocaleString()
                        : '—'}
                    </span>
                  </div>
                  <p className="text-sm font-mono text-light-text dark:text-dark-text truncate">
                    {s.raw_input ?? '(no input)'}
                  </p>
                  <p className="text-xs text-light-muted dark:text-dark-muted font-mono mt-1">
                    session {s.session_id.slice(0, 12)}… · {s.id}
                  </p>
                </div>
                <div className="flex-shrink-0">
                  <Link
                    to={`/admin/demo-sessions/${encodeURIComponent(s.session_id)}`}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold bg-brand-primary text-white rounded-lg hover:bg-brand-primary/90 transition"
                  >
                    Replay
                    <ExternalLink className="w-3 h-3" />
                  </Link>
                </div>
              </div>
            </motion.div>
          ))}
        </div>
      )}
    </div>
  );
}
