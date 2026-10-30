interface PipelineBoxProps {
  emoji: string;
  title: string;
  caption: string;
}

function PipelineBox({ emoji, title, caption }: PipelineBoxProps) {
  return (
    <div className="rounded-xl border border-slate-700 bg-slate-900 p-5 text-center">
      <div className="text-2xl mb-2">{emoji}</div>
      <div className="font-semibold text-slate-200 text-base">{title}</div>
      <div className="text-xs text-slate-500 mt-1">{caption}</div>
    </div>
  );
}

interface FeatureItemProps {
  title: string;
  description: string;
}

function FeatureItem({ title, description }: FeatureItemProps) {
  return (
    <li className="flex gap-3">
      <span className="text-blue-400 mt-0.5 flex-shrink-0">→</span>
      <span>
        <span className="font-semibold text-slate-200">{title}</span>
        <span className="text-slate-400"> — {description}</span>
      </span>
    </li>
  );
}

export function WhatItIs() {
  return (
    <section className="py-32 bg-slate-950 px-4">
      <div className="max-w-5xl mx-auto">
        {/* Section headline */}
        <h2 className="text-4xl md:text-5xl font-bold text-center text-slate-100">
          The engine is done. This is the body.
        </h2>
        <p className="text-xl text-slate-400 text-center mt-4 max-w-2xl mx-auto">
          AEGIS PRO is a pipeline, not a prompt. It runs six stages on every investigation.
        </p>

        {/* Pipeline diagram */}
        <div className="mt-16 max-w-4xl mx-auto">
          {/* Row 1 */}
          <div className="grid grid-cols-3 gap-6 items-center">
            <PipelineBox emoji="📡" title="Watcher" caption="detect" />
            <div className="flex items-center gap-3">
              <span className="text-slate-600 text-lg flex-shrink-0">→</span>
              <PipelineBox emoji="🔍" title="Investigator" caption="diagnose" />
            </div>
            <div className="flex items-center gap-3">
              <span className="text-slate-600 text-lg flex-shrink-0">→</span>
              <PipelineBox emoji="🔧" title="Fixer" caption="fix" />
            </div>
          </div>

          {/* Down arrow on right side */}
          <div className="flex justify-end pr-[calc(50%-0.5rem)] mt-2 mb-2">
            <span className="text-slate-600 text-lg">↓</span>
          </div>

          {/* Row 2 — right to left flow */}
          <div className="grid grid-cols-3 gap-6 items-center">
            <div className="flex items-center gap-3">
              <PipelineBox emoji="🔁" title="Curator" caption="learn" />
              <span className="text-slate-600 text-lg flex-shrink-0">←</span>
            </div>
            <div className="flex items-center gap-3">
              <PipelineBox emoji="📬" title="Communicator" caption="report" />
              <span className="text-slate-600 text-lg flex-shrink-0">←</span>
            </div>
            <PipelineBox emoji="✅" title="Verifier" caption="prove" />
          </div>
        </div>

        {/* Big callout */}
        <div className="mt-16 text-center">
          <p className="text-2xl font-semibold text-slate-100">
            Every fix is verified against the repo&rsquo;s own test suite before it is proposed.
          </p>
          <p className="text-2xl font-semibold text-blue-400 mt-1">
            Not &ldquo;looks good.&rdquo; Proven.
          </p>
        </div>

        {/* Horizontal rule */}
        <hr className="mt-16 border-t border-slate-800" />

        {/* Two-column layout */}
        <div className="mt-16 grid grid-cols-1 md:grid-cols-2 gap-16">
          {/* Left column — feature list */}
          <div>
            <h3 className="text-2xl font-bold text-slate-100">What that gets you</h3>
            <p className="text-base text-slate-500 mt-1">that Cursor and Devin don&rsquo;t</p>
            <ul className="mt-8 space-y-6">
              <FeatureItem
                title="Multi-file detection"
                description="The bug can be in one file, the cause in another, the fix in a third. The scanner traces the whole chain."
              />
              <FeatureItem
                title="Verified fixes"
                description="Every proposed diff is run against the repo's own tests. If they fail, you never see it."
              />
              <FeatureItem
                title="A learning loop"
                description="Every rejection teaches the next scan what not to flag."
              />
              <FeatureItem
                title="Reports, not diffs"
                description="PR comments, Slack messages, weekly digests. The output is something you can forward."
              />
              <FeatureItem
                title="Runs without a prompt"
                description="Scheduled scans, on-PR scans, on-demand. You don't have to ask."
              />
            </ul>
          </div>

          {/* Right column — stats */}
          <div className="space-y-8">
            <div>
              <p className="text-6xl font-bold text-blue-400">799</p>
              <p className="text-sm text-slate-500 mt-1">passing in the current build</p>
            </div>
            <div>
              <p className="text-6xl font-bold text-blue-400">6</p>
              <p className="text-sm text-slate-500 mt-1">
                Watcher · Investigator · Fixer · Verifier · Communicator · Curator
              </p>
            </div>
            <div>
              <p className="text-6xl font-bold text-blue-400">v1.0</p>
              <p className="text-sm text-slate-500 mt-1">already shipped and live in production</p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
