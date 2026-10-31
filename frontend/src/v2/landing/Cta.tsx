interface CtaProps {
  onWatchAgain: () => void;
}

export function Cta({ onWatchAgain }: CtaProps) {
  return (
    <section className="py-24 bg-aegis-bg px-4">
      <div className="max-w-2xl mx-auto text-center space-y-6">
        <h2 className="text-4xl font-bold text-slate-100">
          Bug found. Fix proven. Yours to approve.
        </h2>
        <p className="text-lg text-slate-400 leading-relaxed">
          AEGIS PRO scans your codebase, reproduces the crash, patches it, and runs your tests —
          before you ever see a diff. You review what passed, not what might work.
        </p>
        <div className="flex flex-col sm:flex-row gap-4 justify-center pt-4">
          <a
            href="/demo"
            className="px-6 py-3 bg-aegis-green hover:bg-green-600 text-white font-semibold rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-aegis-amber"
          >
            Try the live demo
          </a>
          <a
            href="https://github.com/MakerYuichi/Aegis-pro"
            target="_blank"
            rel="noopener noreferrer"
            className="px-6 py-3 border border-aegis-line hover:border-slate-500 text-slate-300 hover:text-slate-100 font-semibold rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-aegis-amber"
          >
            View on GitHub
          </a>
        </div>
        <div className="pt-4">
          <button
            onClick={onWatchAgain}
            className="text-sm text-slate-500 hover:text-slate-300 underline underline-offset-4 transition-colors focus:outline-none focus:ring-2 focus:ring-aegis-amber rounded cursor-pointer"
          >
            Watch it again
          </button>
        </div>
      </div>
    </section>
  );
}
