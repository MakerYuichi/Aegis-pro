/**
 * Public demo landing page.
 *
 * Phase 3 (this commit): a placeholder that renders enough to verify the
 * route works without auth. Phase 4 fills in the URL input, the Advanced
 * toggle for stack-trace input, the generated-incident rendering, and the
 * "Reset to default" button.
 */

import { Link } from 'react-router-dom';

export function DemoPage() {
  return (
    <div className="min-h-screen bg-light-bg dark:bg-dark-bg">
      <div className="max-w-4xl mx-auto px-6 py-16">
        <div className="flex items-center justify-between mb-12">
          <div className="flex items-center gap-2">
            <span className="text-2xl">🛡️</span>
            <span className="text-xl font-bold text-light-text dark:text-dark-text">
              AEGIS PRO
            </span>
          </div>
          <Link
            to="/"
            className="text-sm text-light-muted dark:text-dark-muted hover:text-brand-primary transition"
          >
            Sign in
          </Link>
        </div>

        <div className="space-y-6">
          <div>
            <h1 className="text-4xl font-bold text-light-text dark:text-dark-text mb-3">
              AI Incident Commander
            </h1>
            <p className="text-lg text-light-muted dark:text-dark-muted">
              Paste a GitHub repo URL. Watch AEGIS PRO diagnose a realistic
              incident in under 10 seconds — no signup, no credentials,
              nothing touching your actual code.
            </p>
          </div>

          <div className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border p-8 text-center">
            <p className="text-sm text-light-muted dark:text-dark-muted">
              Demo UI ships in the next commit.
            </p>
            <p className="text-xs text-light-muted dark:text-dark-muted mt-2">
              Placeholder — verifies the route works without auth.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
