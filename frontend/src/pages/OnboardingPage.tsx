import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Rocket, CheckCircle, AlertCircle, Mail } from 'lucide-react';
import { motion } from 'framer-motion';
import { useProtectedApi } from '../utils/api';

/**
 * Onboarding placeholder (Phase 10).
 *
 * Phase 11 will build the real onboarding flow — GitHub App install,
 * Slack connection, monitoring setup. Until then, this page captures
 * intent so we know which repos users want to connect.
 *
 * Query params:
 *   ?repo=org/repo   pre-filled from the demo session card
 *
 * The POST is fire-and-forget: the page shows a thank-you whether or
 * not the backend confirms the write. That's deliberate — a failed
 * lead signal should never block the user's path forward.
 */
export function OnboardingPage() {
  const [params] = useSearchParams();
  const { markOnboardingInterest } = useProtectedApi();
  const repo = params.get('repo') || '';
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!repo) {
      setError('No repo specified. Return to the dashboard and try again.');
      return;
    }
    (async () => {
      try {
        await markOnboardingInterest(repo);
        setSubmitted(true);
      } catch {
        // Show the thank-you anyway — the user's intent is clear, and
        // we don't want a backend hiccup to look like a failure.
        setSubmitted(true);
      }
    })();
  }, [repo, markOnboardingInterest]);

  return (
    <div className="max-w-2xl mx-auto py-12">
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        className="bg-light-card dark:bg-dark-card border border-light-border
                   dark:border-dark-border rounded-2xl p-8 text-center space-y-5"
      >
        <div className="p-4 rounded-2xl bg-gradient-to-br from-brand-primary to-brand-secondary inline-block">
          <Rocket className="w-8 h-8 text-white" />
        </div>

        {error ? (
          <>
            <AlertCircle className="w-6 h-6 text-severity-critical mx-auto" />
            <h1 className="text-xl font-bold text-light-text dark:text-dark-text">
              Something went wrong
            </h1>
            <p className="text-sm text-light-muted dark:text-dark-muted">{error}</p>
          </>
        ) : submitted ? (
          <>
            <CheckCircle className="w-6 h-6 text-brand-success mx-auto" />
            <h1 className="text-xl font-bold text-light-text dark:text-dark-text">
              You're on the list
            </h1>
            <p className="text-sm text-light-muted dark:text-dark-muted">
              We'll notify you when onboarding for{' '}
              <span className="font-mono text-brand-primary">{repo}</span>{' '}
              is ready. Real onboarding — GitHub App, Slack, monitoring — is
              shipping in the next phase.
            </p>
            <div className="flex items-center gap-2 justify-center text-xs text-light-muted dark:text-dark-muted pt-2">
              <Mail className="w-3.5 h-3.5" />
              <span>We'll email the address on your account.</span>
            </div>
          </>
        ) : (
          <>
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-brand-primary mx-auto" />
            <p className="text-sm text-light-muted dark:text-dark-muted">
              Recording your interest…
            </p>
          </>
        )}
      </motion.div>
    </div>
  );
}
