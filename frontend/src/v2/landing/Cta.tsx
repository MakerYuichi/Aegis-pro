interface CtaProps {
  onWatchAgain: () => void;
}

export function Cta({ onWatchAgain }: CtaProps) {
  return (
    <section
      className="min-h-screen bg-slate-950 flex flex-col items-center justify-center px-4 text-center"
      style={{ minHeight: '100vh' }}
    >
      <h2 className="text-5xl font-bold tracking-tight text-white leading-tight max-w-3xl">
        This is v2.0.
      </h2>

      <p className="text-lg text-slate-400 mt-8 max-w-2xl leading-relaxed">
        AEGIS PRO v1.0 shipped and is live in production. The pipeline finds bugs, generates fixes,
        and verifies them against the repo&rsquo;s own tests. v2.0 is what that pipeline becomes: an
        ambient agent that works in your editor, in front of you, at human pace. The engine is done.
        This is the body.
      </p>

      <button
        onClick={onWatchAgain}
        className="mt-10 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 font-semibold px-8 py-4 rounded-lg text-lg cursor-pointer transition-colors duration-200"
      >
        Watch it again
      </button>
    </section>
  );
}
