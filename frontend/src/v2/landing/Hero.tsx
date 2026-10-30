interface HeroProps {
  onWatchClick: () => void;
}

export function Hero({ onWatchClick }: HeroProps) {
  return (
    <section className="min-h-screen bg-slate-950 flex flex-col items-center justify-center px-4">
      {/* Wordmark */}
      <p className="text-sm tracking-[0.3em] uppercase text-slate-500 text-center">
        AEGIS PRO
      </p>

      {/* Divider */}
      <div className="w-12 h-px bg-slate-700 mx-auto mt-4 mb-16" />

      {/* Headline */}
      <h1 className="text-7xl md:text-8xl font-bold tracking-tight text-slate-100 text-center">
        Watch the bug get found.
      </h1>

      {/* Body paragraph */}
      <p className="text-xl text-slate-400 max-w-2xl text-center leading-relaxed mx-auto mt-8">
        An AI that reads your code alongside you. When it finds a bug, you watch it work — files
        open, arrows point, code changes, tests run. You see every move. You approve the ones that
        matter.
      </p>

      {/* Category statement */}
      <p className="text-xl text-slate-300 font-medium text-center mt-6">
        It&rsquo;s not a chatbot. It&rsquo;s a colleague.
      </p>

      {/* Primary button */}
      <button
        onClick={onWatchClick}
        className="mt-12 bg-blue-600 hover:bg-blue-500 text-white font-semibold px-10 py-5 rounded-xl text-lg shadow-2xl shadow-blue-500/20 cursor-pointer transition-colors duration-200"
      >
        ▶ Watch it work
      </button>

      {/* Version caption */}
      <p className="text-sm text-slate-500 text-center mt-6">
        v2.0 · The Ambient Agent · 14 seconds
      </p>
    </section>
  );
}
