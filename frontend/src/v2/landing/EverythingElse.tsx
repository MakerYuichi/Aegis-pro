interface CapabilityCardProps {
  icon: string;
  title: string;
  description: string;
}

function CapabilityCard({ icon, title, description }: CapabilityCardProps) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-6">
      <div className="text-2xl mb-3">{icon}</div>
      <h3 className="font-semibold text-slate-200 text-lg">{title}</h3>
      <p className="text-sm text-slate-400 mt-2 leading-relaxed">{description}</p>
    </div>
  );
}

export function EverythingElse() {
  return (
    <section className="py-32 bg-slate-950 px-4">
      <div className="max-w-5xl mx-auto">
        {/* Headline */}
        <h2 className="text-4xl md:text-5xl font-bold text-center text-slate-100">
          The demo shows one bug. The pipeline finds many.
        </h2>

        {/* 2×3 capability grid */}
        <div className="mt-16 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
          <CapabilityCard
            icon="📡"
            title="Proactive scanning"
            description="Scheduled or on-PR. Runs while you sleep, reports when you wake up."
          />
          <CapabilityCard
            icon="🔗"
            title="Multi-file chains"
            description="Traces from crash site to root cause across as many files as it takes."
          />
          <CapabilityCard
            icon="✅"
            title="Verified fixes"
            description="Every diff is proven against the repo's own test suite before you see it."
          />
          <CapabilityCard
            icon="🔁"
            title="Learning loop"
            description="Every rejection teaches the next scan what not to flag. Gets better over time."
          />
          <CapabilityCard
            icon="📬"
            title="Reports everywhere"
            description="PR comments, Slack messages, email digests. The output is forwardable."
          />
          <CapabilityCard
            icon="⏱"
            title="Zero-prompt scans"
            description="Runs on schedule, on-PR, or on-demand. You don't have to ask."
          />
        </div>

        {/* Trust signal */}
        <div className="mt-16 text-center">
          <p className="text-slate-400 text-base">Already in production:</p>
          <p className="text-slate-200 font-semibold text-lg mt-2">
            AEGIS PRO v1.0 · 799 tests · 6 pipeline stages · verified fixes on real repos.
          </p>
        </div>
      </div>
    </section>
  );
}
