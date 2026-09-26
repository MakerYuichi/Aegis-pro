import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Sparkles, ArrowRight, X } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { useProtectedApi, type MyDemoSession } from '../utils/api';

/**
 * Renders a single card on the authenticated dashboard when the user
 * has a linked demo session.
 *
 * States:
 *   - loading  → nothing (avoids flicker)
 *   - no session → nothing
 *   - has session → the card
 *
 * The user can dismiss with the X. Dismissal is per-mount only —
 * it does not persist. Persisting dismissal is a follow-up.
 */
export function DemoSessionCard() {
  const { listMyDemoSessions, markOnboardingInterest } = useProtectedApi();
  const [session, setSession] = useState<MyDemoSession | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await listMyDemoSessions(1);
        if (!cancelled && res.sessions.length > 0) {
          setSession(res.sessions[0]);
        }
      } catch {
        // Non-essential card — swallow. The dashboard works without it.
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [listMyDemoSessions]);

  if (loading || !session || dismissed) {
    return null;
  }

  const repoLabel = `${session.parsed_org}/${session.parsed_repo}`;
  const onboardingHref = `/onboarding?repo=${encodeURIComponent(repoLabel)}`;

  const handleClick = () => {
    // Fire-and-forget. We don't block navigation on this.
    markOnboardingInterest(repoLabel, session.session_id).catch(() => {});
  };

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0 }}
        className="relative bg-gradient-to-br from-brand-primary/10 to-brand-secondary/5
                   border border-brand-primary/30 rounded-2xl p-5 mb-6"
      >
        <button
          onClick={() => setDismissed(true)}
          className="absolute top-3 right-3 p-1.5 rounded-lg
                     hover:bg-light-border/50 dark:hover:bg-dark-border/50 transition"
          aria-label="Dismiss"
        >
          <X className="w-4 h-4 text-light-muted dark:text-dark-muted" />
        </button>

        <div className="flex items-start gap-4 pr-8">
          <div className="p-2.5 rounded-xl bg-gradient-to-br from-brand-primary to-brand-secondary shrink-0">
            <Sparkles className="w-5 h-5 text-white" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-light-text dark:text-dark-text mb-1">
              You tried <span className="font-mono text-brand-primary">{repoLabel}</span> in the demo
            </p>
            <p className="text-xs text-light-muted dark:text-dark-muted mb-3">
              Connect this repo to get real incidents from your own code.
            </p>
            <Link
              to={onboardingHref}
              onClick={handleClick}
              className="inline-flex items-center gap-1.5 text-xs font-semibold
                         text-brand-primary hover:underline"
            >
              Connect it now
              <ArrowRight className="w-3.5 h-3.5" />
            </Link>
          </div>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
