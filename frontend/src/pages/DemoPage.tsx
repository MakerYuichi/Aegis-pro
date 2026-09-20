import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Loader2, Search, AlertTriangle, RotateCcw } from 'lucide-react';
import {
  getDemoDefault,
  generateDemoIncident,
  resetDemo,
  type Incident,
  type DemoGenerateResponse,
} from '../utils/api';
import { IncidentView } from '../components/IncidentView';
import { DemoBadge } from '../components/DemoBadge';

export function DemoPage() {
  const [incident, setIncident] = useState<Incident | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [url, setUrl] = useState('');
  const [error, setError] = useState<{
    reason: string;
    detail: string;
    supported_shapes: string[];
  } | null>(null);
  const [parsedLabel, setParsedLabel] = useState<string | null>(null);

  // Fetch the Aegis-pro default incident on first render.
  useEffect(() => {
    fetchDefault();
  }, []);

  const fetchDefault = async () => {
    try {
      setLoading(true);
      setError(null);
      setParsedLabel(null);
      const data = await getDemoDefault();
      setIncident(data);
    } catch (err) {
      console.error('Failed to fetch default incident:', err);
      setError({
        reason: 'network',
        detail: 'Could not reach the demo backend. Is the orchestrator running?',
        supported_shapes: [],
      });
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!url.trim()) {
      setError({
        reason: 'empty',
        detail: 'Paste a GitHub repo URL to continue.',
        supported_shapes: [],
      });
      return;
    }

    try {
      setSubmitting(true);
      setError(null);
      const response: DemoGenerateResponse = await generateDemoIncident(url);

      if ('error' in response) {
        // Do NOT clear the current incident — the error shows above, the
        // Aegis-pro default stays visible until the user fixes their input.
        setError({
          reason: response.reason,
          detail: response.detail,
          supported_shapes: response.supported_shapes,
        });
        setParsedLabel(null);
      } else {
        setIncident(response.incident);
        setParsedLabel(`${response.parsed.org}/${response.parsed.repo}`);
      }
    } catch (err) {
      console.error('Generate failed:', err);
      setError({
        reason: 'network',
        detail: err instanceof Error ? err.message : 'Request failed',
        supported_shapes: [],
      });
    } finally {
      setSubmitting(false);
    }
  };

  const handleReset = async () => {
    try {
      await resetDemo();
    } catch (err) {
      // Reset failures are harmless — a new cookie will be set on the
      // next generate anyway. Ignore and reset the UI regardless.
      console.warn('Reset failed (non-blocking):', err);
    }
    setUrl('');
    setError(null);
    setParsedLabel(null);
    await fetchDefault();
  };

  return (
    <div className="min-h-screen bg-light-bg dark:bg-dark-bg">
      <div className="max-w-6xl mx-auto px-6 py-12">
        {/* Header */}
        <div className="flex items-center justify-between mb-10">
          <div className="flex items-center gap-2">
            <span className="text-2xl">🛡️</span>
            <span className="text-xl font-bold text-light-text dark:text-dark-text">
              AEGIS PRO
            </span>
          </div>
          <Link
            to="/"
            className="text-sm font-medium text-brand-primary hover:underline"
          >
            Sign in →
          </Link>
        </div>

        {/* Hero */}
        <div className="mb-8">
          <h1 className="text-4xl font-bold text-light-text dark:text-dark-text mb-3">
            AI Incident Commander
          </h1>
          <p className="text-lg text-light-muted dark:text-dark-muted">
            Paste a GitHub repo URL. Watch AEGIS PRO diagnose a realistic
            incident in under 10 seconds — no signup, no credentials,
            nothing touching your actual code.
          </p>
        </div>

        {/* Input form */}
        <form onSubmit={handleSubmit} className="mb-8">
          <div className="flex flex-col sm:flex-row gap-3">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-light-muted dark:text-dark-muted" />
              <input
                type="text"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://github.com/your-org/your-repo"
                className="w-full pl-10 pr-4 py-3 bg-light-card dark:bg-dark-card border border-light-border dark:border-dark-border rounded-xl text-light-text dark:text-dark-text focus:outline-none focus:ring-2 focus:ring-brand-primary/30"
                disabled={submitting}
              />
            </div>
            <button
              type="submit"
              disabled={submitting}
              className="flex items-center justify-center gap-2 px-6 py-3 bg-brand-primary text-white rounded-xl hover:bg-brand-primary/90 transition font-semibold disabled:opacity-50"
            >
              {submitting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Analyzing...
                </>
              ) : (
                'Analyze Repository'
              )}
            </button>
          </div>
        </form>

        {/* Error state — inline, does not hide the default incident */}
        {error && (
          <div className="mb-8 bg-severity-critical/10 border border-severity-critical/30 rounded-2xl p-5">
            <div className="flex items-start gap-3">
              <AlertTriangle className="w-5 h-5 text-severity-critical mt-0.5 flex-shrink-0" />
              <div className="flex-1">
                <p className="text-sm font-semibold text-severity-critical mb-1">
                  Could not parse that URL. Reason: {error.reason}
                </p>
                <p className="text-sm text-light-muted dark:text-dark-muted mb-3">
                  {error.detail}
                </p>
                {error.supported_shapes.length > 0 && (
                  <div className="text-xs text-light-muted dark:text-dark-muted">
                    <p className="font-medium mb-1">Supported formats:</p>
                    <ul className="space-y-0.5 font-mono">
                      {error.supported_shapes.map((shape) => (
                        <li key={shape}>{shape}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Parsed label + reset button, shown after a successful generate */}
        {parsedLabel && (
          <div className="mb-6 flex items-center justify-between flex-wrap gap-3">
            <div className="flex items-center gap-3">
              <span className="text-sm text-light-muted dark:text-dark-muted">
                Showing incident for
              </span>
              <span className="text-sm font-semibold text-light-text dark:text-dark-text">
                {parsedLabel}
              </span>
              <DemoBadge />
            </div>
            <button
              onClick={handleReset}
              className="flex items-center gap-2 px-3 py-1.5 text-sm text-light-muted dark:text-dark-muted hover:text-brand-primary transition"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              Reset to default
            </button>
          </div>
        )}

        {/* Demo banner — only when showing the Aegis-pro default */}
        {!parsedLabel && incident && !loading && (
          <div className="mb-6 flex items-center gap-3 flex-wrap">
            <DemoBadge />
            <span className="text-sm text-light-muted dark:text-dark-muted">
              Showing sample incident from{' '}
              <code className="font-mono text-light-text dark:text-dark-text">
                MakerYuichi/Aegis-pro
              </code>
              . Paste a GitHub repo URL above to try your own.
            </span>
          </div>
        )}

        {/* Incident rendering */}
        {loading ? (
          <div className="flex justify-center items-center h-64">
            <Loader2 className="w-8 h-8 text-brand-primary animate-spin" />
          </div>
        ) : incident ? (
          <IncidentView incident={incident} demoMode />
        ) : null}
      </div>
    </div>
  );
}
