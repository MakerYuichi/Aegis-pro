import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Loader2,
  Search,
  AlertTriangle,
  RotateCcw,
  FileCode,
  GitCommit,
  GitPullRequest,
  Sparkles,
  ExternalLink,
  ChevronDown,
  FileStack,
} from "lucide-react";
import {
  getDemoDefault,
  generateDemoIncident,
  regenerateDemoIncident,
  resetDemo,
  type Incident,
  type DemoGenerateResponse,
  type DemoTimings,
  type DemoCandidate,
} from "../utils/api";
import { IncidentView } from "../components/IncidentView";
import { DemoBadge } from "../components/DemoBadge";
import {
  PipelineProgress,
  type PipelineStage,
} from "../components/PipelineProgress";

const STAGE_DEFS: PipelineStage[] = [
  { key: "parse_ms", label: "Parsing repo signature" },
  { key: "fetch_meta_ms", label: "Fetching metadata" },
  { key: "fetch_tree_ms", label: "Fetching file tree" },
  { key: "select_file_ms", label: "Selecting incident surface" },
  { key: "fetch_file_ms", label: "Retrieving source file" },
  { key: "fetch_commits_ms", label: "Retrieving file history" },
  { key: "fetch_contributors_ms", label: "Retrieving contributors" },
  { key: "fetch_recent_prs_ms", label: "Retrieving recent PRs" },
  { key: "analyze_ms", label: "Analyzing source for risks" },
  { key: "fetch_file_prs_ms", label: "Scoring related PRs" },
  { key: "generate_ms", label: "Generating patch approval" },
];

type ViewState = "landing" | "analyzing" | "result";

type ErrorState = {
  reason: string;
  detail: string;
  supported_shapes: string[];
  signupRequired?: boolean;
};

export function DemoPage() {
  const [view, setView] = useState<ViewState>("landing");
  const [defaultIncident, setDefaultIncident] = useState<Incident | null>(null);
  const [incident, setIncident] = useState<Incident | null>(null);
  const [loading, setLoading] = useState(true);
  const [url, setUrl] = useState("");
  const [error, setError] = useState<ErrorState | null>(null);
  const [parsedLabel, setParsedLabel] = useState<string | null>(null);
  const [timings, setTimings] = useState<DemoTimings | null>(null);
  const [triesRemaining, setTriesRemaining] = useState<number | null>(null);
  const [sampleExpanded, setSampleExpanded] = useState(false);

  // Dropdown state
  const [candidates, setCandidates] = useState<DemoCandidate[]>([]);
  const [currentFile, setCurrentFile] = useState<string | null>(null);
  const [regenerating, setRegenerating] = useState(false);

  useEffect(() => {
    fetchDefault();
  }, []);

  const fetchDefault = async () => {
    try {
      setLoading(true);
      setError(null);
      setParsedLabel(null);
      setTimings(null);
      setCandidates([]);
      setCurrentFile(null);
      const data = await getDemoDefault();
      setDefaultIncident(data);
      setIncident(data);
    } catch (err) {
      console.error("Failed to fetch default incident:", err);
      setError({
        reason: "network",
        detail:
          "Could not reach the demo backend. Is the orchestrator running?",
        supported_shapes: [],
      });
    } finally {
      setLoading(false);
    }
  };

  const applyResponse = (response: DemoGenerateResponse) => {
    if ("reason" in response) {
      setError({
        reason: response.reason,
        detail: response.detail,
        supported_shapes: response.supported_shapes ?? [],
        signupRequired: response.signup_required,
      });
      setTriesRemaining(response.tries_remaining ?? null);
      return false;
    }
    setIncident(response.incident);
    setParsedLabel(`${response.parsed.org}/${response.parsed.repo}`);
    setTimings(response.meta.timings ?? null);
    setTriesRemaining(response.meta.tries_remaining);
    setCandidates(response.incident.extra_metadata?.demo_candidates ?? []);
    setCurrentFile(response.incident.file_path ?? null);
    return true;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!url.trim()) {
      setError({
        reason: "empty",
        detail: "Paste a public GitHub repo URL to continue.",
        supported_shapes: [],
      });
      return;
    }

    setView("analyzing");
    setError(null);
    setTimings(null);

    try {
      const response: DemoGenerateResponse = await generateDemoIncident(url);
      const ok = applyResponse(response);
      setView(ok ? "result" : "landing");
    } catch (err) {
      console.error("Generate failed:", err);
      setError({
        reason: "network",
        detail: err instanceof Error ? err.message : "Request failed",
        supported_shapes: [],
      });
      setView("landing");
    }
  };

  const handleFileSwitch = async (filePath: string) => {
    if (!parsedLabel || filePath === currentFile || regenerating) return;

    // parsedLabel is "org/repo"; we need the URL form.
    const repoUrl = `github.com/${parsedLabel}`;

    setRegenerating(true);
    setError(null);

    try {
      const response = await regenerateDemoIncident(repoUrl, filePath);
      const ok = applyResponse(response);
      if (!ok) {
        // Keep the previous incident visible; the error banner shows why.
      }
    } catch (err) {
      console.error("Regenerate failed:", err);
      setError({
        reason: "network",
        detail: err instanceof Error ? err.message : "Request failed",
        supported_shapes: [],
      });
    } finally {
      setRegenerating(false);
    }
  };

  const handleReset = async () => {
    try {
      await resetDemo();
    } catch (err) {
      console.warn("Reset failed (non-blocking):", err);
    }
    setUrl("");
    setError(null);
    setParsedLabel(null);
    setTimings(null);
    setTriesRemaining(null);
    setCandidates([]);
    setCurrentFile(null);
    setIncident(defaultIncident);
    setView("landing");
  };

  const pipelineStages: PipelineStage[] = STAGE_DEFS.map((s) => ({
    ...s,
    realMs: timings ? (timings as any)[s.key] : undefined,
  }));

  const showRealDataBanner =
    parsedLabel && incident?.extra_metadata?.demo_quality?.real_file;

  // ── State 2: Analyzing ───────────────────────────────────────────────
  if (view === "analyzing") {
    return (
      <div className="min-h-screen bg-light-bg dark:bg-dark-bg flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-2xl">
          <div className="text-center mb-10">
            <div className="inline-flex items-center gap-2 mb-6">
              <span className="text-3xl">🛡️</span>
              <span className="text-2xl font-bold text-light-text dark:text-dark-text">
                AEGIS PRO
              </span>
            </div>
            <h2 className="text-3xl font-bold text-light-text dark:text-dark-text mb-2">
              Analyzing your repository
            </h2>
            <p className="text-light-muted dark:text-dark-muted font-mono text-sm">
              {url}
            </p>
          </div>
          <PipelineProgress stages={pipelineStages} completed={false} />
        </div>
      </div>
    );
  }

  // ── State 3: Result ──────────────────────────────────────────────────
  if (view === "result" && incident) {
    return (
      <div className="min-h-screen bg-light-bg dark:bg-dark-bg">
        <div className="max-w-6xl mx-auto px-6 py-12">
          <div className="flex items-center justify-between mb-8">
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

          {/* Real-data banner */}
          {showRealDataBanner && (
            <div className="mb-6 bg-gradient-to-r from-brand-success/10 to-brand-primary/10 border border-brand-success/30 rounded-2xl p-5">
              <div className="flex items-center gap-2 mb-3">
                <DemoBadge />
                <span className="text-sm font-semibold text-light-text dark:text-dark-text">
                  Real analysis of{" "}
                  <code className="font-mono">github.com/{parsedLabel}</code>
                </span>
              </div>
              <div className="flex flex-wrap gap-4 text-sm">
                <a
                  href={`https://github.com/${parsedLabel}/blob/HEAD/${incident.file_path}#L${incident.line_number}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1.5 text-brand-primary hover:underline"
                >
                  <FileCode className="w-3.5 h-3.5" />
                  {incident.file_path}:{incident.line_number}
                  <ExternalLink className="w-3 h-3" />
                </a>
                {incident.extra_metadata?.github?.blame?.author && (
                  <a
                    href={`https://github.com/${incident.extra_metadata.github.blame.author}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1.5 text-brand-primary hover:underline"
                  >
                    <GitCommit className="w-3.5 h-3.5" />
                    {incident.extra_metadata.github.blame.author}
                    <ExternalLink className="w-3 h-3" />
                  </a>
                )}
                {incident.extra_metadata?.github?.blame?.pr_number && (
                  <a
                    href={incident.extra_metadata.github.blame.pr_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1.5 text-brand-primary hover:underline"
                  >
                    <GitPullRequest className="w-3.5 h-3.5" />
                    PR #{incident.extra_metadata.github.blame.pr_number}
                    <ExternalLink className="w-3 h-3" />
                  </a>
                )}
              </div>
            </div>
          )}

          {/* Parsed label + reset */}
          <div className="mb-6 flex items-center justify-between flex-wrap gap-3">
            <div className="flex items-center gap-3">
              <span className="text-sm text-light-muted dark:text-dark-muted">
                Showing incident for
              </span>
              <span className="text-sm font-semibold text-light-text dark:text-dark-text">
                {parsedLabel}
              </span>
              <DemoBadge />
              {triesRemaining !== null && triesRemaining > 0 && (
                <span className="text-xs text-light-muted dark:text-dark-muted">
                  · {triesRemaining} {triesRemaining === 1 ? "try" : "tries"}{" "}
                  remaining
                </span>
              )}
            </div>
            <button
              onClick={handleReset}
              className="flex items-center gap-2 px-3 py-1.5 text-sm text-light-muted dark:text-dark-muted hover:text-brand-primary transition"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              Try another repo
            </button>
          </div>

          {/* ── File dropdown ──────────────────────────────────────────── */}
          {candidates.length > 1 && (
            <div className="mb-6 bg-light-card dark:bg-dark-card rounded-xl border border-light-border dark:border-dark-border p-4">
              <div className="flex items-center gap-3 flex-wrap">
                <div className="flex items-center gap-2 text-sm text-light-muted dark:text-dark-muted">
                  <FileStack className="w-4 h-4 text-brand-primary" />
                  <span>Try a different file:</span>
                </div>
                <div className="relative flex-1 min-w-[260px]">
                  <select
                    value={currentFile ?? ""}
                    onChange={(e) => handleFileSwitch(e.target.value)}
                    disabled={regenerating}
                    className="w-full appearance-none pl-3 pr-10 py-2 bg-light-bg dark:bg-dark-bg border border-light-border dark:border-dark-border rounded-lg text-sm text-light-text dark:text-dark-text font-mono focus:outline-none focus:ring-2 focus:ring-brand-primary/30 disabled:opacity-50"
                  >
                    {candidates.map((c) => (
                      <option key={c.path} value={c.path}>
                        {c.path}
                      </option>
                    ))}
                  </select>
                  {regenerating ? (
                    <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-brand-primary animate-spin" />
                  ) : (
                    <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-light-muted dark:text-dark-muted pointer-events-none" />
                  )}
                </div>
              </div>
              <p className="text-xs text-light-muted dark:text-dark-muted mt-2">
                {regenerating
                  ? "Analyzing a different file from your repo…"
                  : candidates.length === 5
                    ? "AEGIS PRO picked the highest-scoring file. Switch to see the analysis for another."
                    : `${candidates.length} candidate files found.`}
              </p>
            </div>
          )}

          {/* Error banner (also covers paid-switch signup_required) */}
          {error && (
            <div className="mb-6 bg-severity-critical/10 border border-severity-critical/30 rounded-2xl p-5">
              <div className="flex items-start gap-3">
                <AlertTriangle className="w-5 h-5 text-severity-critical mt-0.5 flex-shrink-0" />
                <div className="flex-1">
                  {error.signupRequired ? (
                    <>
                      <p className="text-sm font-semibold text-severity-critical mb-1">
                        You've used all your free demo analyses.
                      </p>
                      <p className="text-sm text-light-muted dark:text-dark-muted mb-3">
                        {error.detail}
                      </p>
                      <Link
                        to="/"
                        className="inline-flex items-center gap-2 px-4 py-2 bg-brand-primary text-white rounded-lg text-sm font-semibold hover:bg-brand-primary/90 transition"
                      >
                        Join Cloud Beta
                        <ExternalLink className="w-3 h-3" />
                      </Link>
                    </>
                  ) : (
                    <>
                      <p className="text-sm font-semibold text-severity-critical mb-1">
                        Could not switch to that file.
                      </p>
                      <p className="text-sm text-light-muted dark:text-dark-muted">
                        {error.detail}
                      </p>
                    </>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Timings */}
          {timings && (
            <div className="mb-8">
              <PipelineProgress stages={pipelineStages} completed />
            </div>
          )}

          {/* Incident */}
          <IncidentView incident={incident} demoMode />
        </div>
      </div>
    );
  }

  // ── State 1: Landing ─────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-light-bg dark:bg-dark-bg">
      <section className="min-h-[88vh] flex flex-col">
        <div className="px-6 py-5 flex items-center justify-between">
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

        <div className="flex-1 flex items-center justify-center px-6">
          <div className="max-w-3xl w-full text-center">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-brand-primary/10 text-brand-primary text-xs font-semibold mb-6">
              <Sparkles className="w-3 h-3" />
              LIVE DEMO · NO SIGNUP REQUIRED
            </div>

            <h1 className="text-5xl sm:text-6xl font-bold text-light-text dark:text-dark-text mb-5 leading-[1.05]">
              Paste a repo.
              <br />
              Watch AEGIS PRO find a{" "}
              <span className="text-brand-primary">real bug.</span>
            </h1>

            <p className="text-lg text-light-muted dark:text-dark-muted mb-10 max-w-2xl mx-auto">
              AEGIS PRO reads your actual source files, identifies production
              risks with an LLM, and generates a patch approval — in under 10
              seconds.
            </p>

            <form onSubmit={handleSubmit} className="mb-4">
              <div className="flex flex-col sm:flex-row gap-3 max-w-2xl mx-auto">
                <div className="relative flex-1">
                  <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-light-muted dark:text-dark-muted" />
                  <input
                    type="text"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    placeholder="https://github.com/your-org/your-repo"
                    className="w-full pl-11 pr-4 py-4 bg-light-card dark:bg-dark-card border border-light-border dark:border-dark-border rounded-xl text-light-text dark:text-dark-text text-base focus:outline-none focus:ring-2 focus:ring-brand-primary/30 focus:border-brand-primary/50"
                    disabled={loading}
                    autoFocus
                  />
                </div>
                <button
                  type="submit"
                  disabled={loading}
                  className="flex items-center justify-center gap-2 px-7 py-4 bg-brand-primary text-white rounded-xl hover:bg-brand-primary/90 transition font-semibold text-base disabled:opacity-50 whitespace-nowrap"
                >
                  Analyze Repository
                </button>
              </div>
            </form>

            <p className="text-xs text-light-muted dark:text-dark-muted">
              No signup. No token. Nothing touched. Read-only access to public
              repos.
            </p>

            {triesRemaining !== null && triesRemaining > 0 && (
              <p className="text-xs text-light-muted dark:text-dark-muted mt-2">
                {triesRemaining} {triesRemaining === 1 ? "try" : "tries"}{" "}
                remaining this session
              </p>
            )}

            {error && (
              <div className="mt-6 bg-severity-critical/10 border border-severity-critical/30 rounded-2xl p-5 text-left max-w-2xl mx-auto">
                <div className="flex items-start gap-3">
                  <AlertTriangle className="w-5 h-5 text-severity-critical mt-0.5 flex-shrink-0" />
                  <div className="flex-1">
                    {error.signupRequired ? (
                      <>
                        <p className="text-sm font-semibold text-severity-critical mb-1">
                          You've used all your free demo analyses.
                        </p>
                        <p className="text-sm text-light-muted dark:text-dark-muted mb-3">
                          {error.detail}
                        </p>
                        <Link
                          to="/"
                          className="inline-flex items-center gap-2 px-4 py-2 bg-brand-primary text-white rounded-lg text-sm font-semibold hover:bg-brand-primary/90 transition"
                        >
                          Join Cloud Beta
                          <ExternalLink className="w-3 h-3" />
                        </Link>
                      </>
                    ) : (
                      <>
                        <p className="text-sm font-semibold text-severity-critical mb-1">
                          {error.reason === "not_code"
                            ? "This repo doesn't contain code that can fail."
                            : error.reason === "empty_repo"
                              ? "This repo is empty."
                              : error.reason === "not_found"
                                ? "Repo not found on GitHub."
                                : error.reason === "rate_limited"
                                  ? "GitHub rate limit reached."
                                  : error.reason === "no_risk_found"
                                    ? "No specific failure found."
                                    : "Could not analyze that repo."}
                        </p>
                        <p className="text-sm text-light-muted dark:text-dark-muted mb-3">
                          {error.detail}
                        </p>
                        {error.supported_shapes.length > 0 && (
                          <div className="text-xs text-light-muted dark:text-dark-muted">
                            <p className="font-medium mb-1">
                              Supported formats:
                            </p>
                            <ul className="space-y-0.5 font-mono">
                              {error.supported_shapes.map((shape) => (
                                <li key={shape}>{shape}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="pb-6 text-center">
          <ChevronDown className="w-5 h-5 text-light-muted dark:text-dark-muted mx-auto animate-bounce" />
        </div>
      </section>

      <section className="border-t border-light-border dark:border-dark-border bg-light-surface dark:bg-dark-surface py-16 px-6">
        <div className="max-w-4xl mx-auto">
          <div className="text-center mb-8">
            <span className="text-xs font-semibold tracking-[0.2em] text-brand-primary uppercase">
              Sample Output
            </span>
            <h2 className="text-2xl font-bold text-light-text dark:text-dark-text mt-2">
              What you'll get back
            </h2>
          </div>

          {loading ? (
            <div className="flex justify-center items-center h-32">
              <Loader2 className="w-6 h-6 text-brand-primary animate-spin" />
            </div>
          ) : defaultIncident ? (
            <div className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border overflow-hidden">
              <div className="p-6">
                <div className="flex items-center gap-3 mb-3 flex-wrap">
                  <span className="px-3 py-1 rounded-full text-xs font-semibold bg-severity-critical/10 text-severity-critical border border-severity-critical/30">
                    {defaultIncident.severity}
                  </span>
                  <span className="text-sm font-semibold text-light-text dark:text-dark-text">
                    {defaultIncident.title}
                  </span>
                  <DemoBadge />
                </div>
                <p className="text-sm text-light-muted dark:text-dark-muted mb-4">
                  {defaultIncident.root_cause.slice(0, 220)}…
                </p>
                <div className="flex items-center justify-between flex-wrap gap-3">
                  <div className="flex items-center gap-3 text-xs text-light-muted dark:text-dark-muted">
                    <span>{defaultIncident.service_name}</span>
                    <span>·</span>
                    <span>
                      {defaultIncident.affected_services.length} services
                      affected
                    </span>
                    <span>·</span>
                    <span>
                      {Math.round(defaultIncident.confidence_score * 100)}%
                      confidence
                    </span>
                  </div>
                  <button
                    onClick={() => setSampleExpanded((s) => !s)}
                    className="flex items-center gap-1.5 text-sm font-medium text-brand-primary hover:underline"
                  >
                    {sampleExpanded ? "Hide details" : "View full sample"}
                    <ChevronDown
                      className={`w-3.5 h-3.5 transition-transform ${
                        sampleExpanded ? "rotate-180" : ""
                      }`}
                    />
                  </button>
                </div>
              </div>

              {sampleExpanded && (
                <div className="border-t border-light-border dark:border-dark-border p-6">
                  <IncidentView incident={defaultIncident} demoMode />
                </div>
              )}
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}
