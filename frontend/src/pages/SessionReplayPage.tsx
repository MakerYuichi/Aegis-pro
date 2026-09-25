/**
 * SessionReplayPage — full replay of a single demo session.
 *
 * A session can contain multiple calls: the buyer pastes a URL, gets an
 * incident, then uses the file dropdown to regenerate. This page shows
 * every call in order, with the decoded incident payload for each.
 *
 * Use case: preparing for a discovery call. "Here's the repo they tried,
 * here's the file we found, here's what they saw."
 *
 * Route: /admin/demo-sessions/:id
 */
import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  RefreshCw, ArrowLeft, CheckCircle, XCircle, Clock,
  ExternalLink, FileCode,
} from 'lucide-react';
import { motion } from 'framer-motion';
import { useAdminApi, type AdminDemoSessionDetail } from '../utils/api';
import { IncidentView } from '../components/IncidentView';

export function SessionReplayPage() {
  const { id } = useParams<{ id: string }>();
  const adminApi = useAdminApi();
  const [detail, setDetail] = useState<AdminDemoSessionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedCallId, setExpandedCallId] = useState<number | null>(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;

    (async () => {
      try {
        setLoading(true);
        setError(null);
        const data = await adminApi.fetchSessionDetail(id);
        if (!cancelled) setDetail(data);
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : 'Failed to load session'
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <RefreshCw className="w-7 h-7 text-brand-primary animate-spin mx-auto" />
          <p className="mt-3 text-sm text-light-muted dark:text-dark-muted">
            Loading session…
          </p>
        </div>
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div className="space-y-4">
        <Link
          to="/admin/demo-activity"
          className="inline-flex items-center gap-1.5 text-sm text-brand-primary hover:underline"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Back to activity
        </Link>
        <div className="bg-severity-critical/10 border border-severity-critical/30 rounded-xl p-4 text-sm text-severity-critical">
          {error ?? 'Session not found.'}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <p className="text-sm text-light-muted dark:text-dark-muted font-mono mt-1">
          {detail.session_id}
        </p>
        <div className="flex items-center gap-3 mt-2 text-xs text-light-muted dark:text-dark-muted">
          <span className="flex items-center gap-1">
            <Clock className="w-3 h-3" />
            First seen {detail.first_seen
              ? new Date(detail.first_seen).toLocaleString()
              : '—'}
          </span>
          <span>·</span>
          <span>{detail.call_count} call{detail.call_count !== 1 ? 's' : ''}</span>
        </div>
      </div>

      {/* Calls */}
      <div className="space-y-3">
        {detail.calls.map((call, idx) => {
          const expanded = expandedCallId === call.id;
          return (
            <motion.div
              key={call.id}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: Math.min(idx * 0.04, 0.3) }}
              className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border overflow-hidden"
            >
              {/* Call header */}
              <div className="px-5 py-4">
                <div className="flex items-start gap-4">
                  <div className="flex-shrink-0 mt-0.5">
                    {call.parse_ok ? (
                      <CheckCircle className="w-5 h-5 text-brand-success" />
                    ) : (
                      <XCircle className="w-5 h-5 text-severity-critical" />
                    )}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap mb-1">
                      <span className="text-xs text-light-muted dark:text-dark-muted font-mono">
                        #{idx + 1}
                      </span>
                      {call.parsed_org && (
                        <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-brand-primary/10 text-brand-primary border border-brand-primary/20 font-mono">
                          {call.parsed_org}/{call.parsed_repo ?? '?'}
                        </span>
                      )}
                      {call.language_inferred && (
                        <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-light-surface dark:bg-dark-surface text-light-muted dark:text-dark-muted border border-light-border dark:border-dark-border">
                          {call.language_inferred}
                        </span>
                      )}
                      {!call.parse_ok && call.error_reason && (
                        <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-severity-critical/10 text-severity-critical border border-severity-critical/25">
                          {call.error_reason}
                        </span>
                      )}
                      <span className="text-xs text-light-muted dark:text-dark-muted flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        {call.created_at
                          ? new Date(call.created_at).toLocaleString()
                          : '—'}
                      </span>
                    </div>
                    <p className="text-sm font-mono text-light-text dark:text-dark-text truncate">
                      {call.raw_input ?? '(no input)'}
                    </p>
                  </div>
                  {call.incident_payload && (
                    <button
                      onClick={() =>
                        setExpandedCallId(expanded ? null : call.id)
                      }
                      className="flex-shrink-0 flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold bg-brand-primary text-white rounded-lg hover:bg-brand-primary/90 transition"
                    >
                      <FileCode className="w-3.5 h-3.5" />
                      {expanded ? 'Hide' : 'View incident'}
                    </button>
                  )}
                </div>
              </div>

              {/* Expanded incident */}
              {expanded && call.incident_payload && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  className="border-t border-light-border dark:border-dark-border bg-light-surface dark:bg-dark-surface px-5 py-5"
                >
                  <div className="flex items-center justify-between mb-4">
                    <p className="text-xs font-semibold uppercase tracking-wide text-light-muted dark:text-dark-muted">
                      Incident payload
                    </p>
                    {call.incident_id && (
                      <Link
                        to={`/incident/${call.incident_id}`}
                        className="flex items-center gap-1.5 text-xs text-brand-primary hover:underline"
                      >
                        Open in dashboard
                        <ExternalLink className="w-3 h-3" />
                      </Link>
                    )}
                  </div>
                  <IncidentView incident={call.incident_payload} demoMode />
                </motion.div>
              )}
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}
