interface CtaProps {
  onWatchAgain: () => void;
}

export function Cta({ onWatchAgain }: CtaProps) {
  return (
    <section className="min-h-screen flex items-center justify-center bg-slate-950 px-4">
      <div className="max-w-2xl mx-auto text-center space-y-8">
        {/* Headline */}
        <h2 className="text-5xl md:text-6xl font-bold text-slate-100">
          This is v2.0.
        </h2>

        {/* Paragraph 1 */}
        <p className="text-xl text-slate-400 leading-relaxed">
          AEGIS PRO v1.0 shipped and is live in production. The pipeline finds bugs, generates
          fixes, and verifies them against the repo&rsquo;s own tests.
        </p>

        {/* Paragraph 2 */}
        <p className="text-xl text-slate-400 leading-relaxed">
          v2.0 is what that pipeline becomes: an ambient agent that works in your editor, in front
          of you, at human pace.
        </p>

        {/* Closing line */}
        <p className="text-2xl text-slate-200 font-semibold">
          The engine is done. This is the body.
        </p>

        {/* Button */}
        <button
          onClick={onWatchAgain}
          className="border border-slate-600 hover:border-slate-400 text-slate-300 hover:text-slate-100 font-semibold px-8 py-4 rounded-xl text-lg transition-colors duration-200 cursor-pointer"
        >
          Watch it again
        </button>
      </div>
    </section>
  );
}
