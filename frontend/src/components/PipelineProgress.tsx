import { useEffect, useState } from 'react';
import { Check, Loader2 } from 'lucide-react';

export type PipelineStage = {
  key: string;
  label: string;
  // ms from the real response, filled in when the request completes.
  realMs?: number;
};

type PipelineProgressProps = {
  stages: PipelineStage[];
  // When the request finishes, we know the real timings. Pass them in
  // to replace the fake animated values.
  completed: boolean;
};

const FAKE_STAGE_MS = 500;

export function PipelineProgress({ stages, completed }: PipelineProgressProps) {
  const [visibleCount, setVisibleCount] = useState(0);

  useEffect(() => {
    if (completed) {
      setVisibleCount(stages.length);
      return;
    }
    // Advance the fake progress every FAKE_STAGE_MS until all stages show.
    if (visibleCount < stages.length) {
      const t = setTimeout(() => setVisibleCount((c) => c + 1), FAKE_STAGE_MS);
      return () => clearTimeout(t);
    }
  }, [visibleCount, stages.length, completed]);

  const totalReal = stages.reduce((sum, s) => sum + (s.realMs || 0), 0);

  return (
    <div className="bg-light-card dark:bg-dark-card rounded-2xl border border-light-border dark:border-dark-border p-6">
      <div className="flex items-center gap-2 mb-4">
        <Loader2
          className={`w-4 h-4 text-brand-primary ${
            completed ? '' : 'animate-spin'
          }`}
        />
        <span className="text-sm font-semibold text-light-text dark:text-dark-text">
          {completed ? 'Analysis complete' : 'Analyzing repository'}
        </span>
      </div>

      <div className="space-y-2 font-mono text-xs">
        {stages.map((stage, i) => {
          const shown = i < visibleCount;
          const realMs = stage.realMs;
          return (
            <div
              key={stage.key}
              className={`flex items-center justify-between transition-opacity duration-200 ${
                shown ? 'opacity-100' : 'opacity-0'
              }`}
            >
              <div className="flex items-center gap-2">
                <Check className="w-3 h-3 text-brand-success" />
                <span className="text-light-text dark:text-dark-text">
                  {stage.label}
                </span>
              </div>
              <span className="text-light-muted dark:text-dark-muted">
                {completed && realMs !== undefined
                  ? `${(realMs / 1000).toFixed(1)}s`
                  : `${(FAKE_STAGE_MS / 1000).toFixed(1)}s`}
              </span>
            </div>
          );
        })}
      </div>

      {completed && (
        <div className="mt-4 pt-4 border-t border-light-border dark:border-dark-border flex items-center justify-between">
          <span className="text-xs text-light-muted dark:text-dark-muted">
            Total
          </span>
          <span className="text-sm font-semibold text-brand-primary">
            {(totalReal / 1000).toFixed(1)}s
          </span>
        </div>
      )}
    </div>
  );
}
