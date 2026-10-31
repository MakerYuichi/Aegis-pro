const STEPS = [
  { label: 'Found', color: 'text-aegis-amber', border: 'border-aegis-amber/40', bg: 'bg-aegis-amber/10', desc: 'Agent reads the file and locates the crash site.' },
  { label: 'Reproduced', color: 'text-aegis-red', border: 'border-aegis-red/40', bg: 'bg-aegis-red/10', desc: 'Probe runs the code and confirms the crash.' },
  { label: 'Fixed', color: 'text-aegis-green', border: 'border-aegis-green/40', bg: 'bg-aegis-green/10', desc: 'A minimal patch is generated and applied.' },
  { label: 'Re-run', color: 'text-aegis-green', border: 'border-aegis-green/40', bg: 'bg-aegis-green/10', desc: 'Probe runs again to verify the fix passes.' },
];

export function VerifierFlow() {
  return (
    <section className="py-20 bg-aegis-bg px-4 border-t border-aegis-line">
      <div className="max-w-5xl mx-auto">
        <h2 className="text-2xl font-bold text-slate-100 mb-10 text-center">How the verifier works</h2>
        <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4">
          {STEPS.map((step, idx) => (
            <div key={step.label} className="flex items-center gap-3 sm:flex-1">
              <div
                className={`flex-1 rounded-lg border p-4 ${step.border} ${step.bg}`}
              >
                <p className={`font-semibold text-sm ${step.color}`}>{step.label}</p>
                <p className="text-xs text-slate-400 mt-1 leading-relaxed">{step.desc}</p>
              </div>
              {idx < STEPS.length - 1 && (
                <span className="text-slate-600 text-lg flex-shrink-0 hidden sm:block">→</span>
              )}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
