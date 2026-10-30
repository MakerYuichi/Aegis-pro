interface HeroProps {
  onWatchClick: () => void;
}

export function Hero({ onWatchClick }: HeroProps) {
  return (
    <section
      className="min-h-screen bg-slate-950 flex flex-col items-center justify-center px-4 text-center"
      style={{ minHeight: '100vh' }}
    >
      {/* Wordmark */}
      <p className="text-sm tracking-widest text-slate-500 uppercase mb-8">
        AEGIS PRO
      </p>

      <h1
        className="font-bold tracking-tight text-white"
        style={{ fontSize: 'clamp(3rem, 8vw, 6rem)', lineHeight: 1.05 }}
      >
        Watch the bug get found.
      </h1>

      <p className="text-xl md:text-2xl text-slate-400 mt-6 max-w-3xl leading-relaxed">
        An AI that investigates your code, live. Every arrow, every callout, every fix — visible.
      </p>

      <button
        onClick={onWatchClick}
        className="bg-blue-600 hover:bg-blue-500 text-white font-semibold px-8 py-4 rounded-lg text-lg mt-10 cursor-pointer transition-colors duration-200 shadow-xl shadow-blue-500/20"
      >
        ▶ Watch it work
      </button>

      <p className="text-sm text-slate-500 mt-4">
        v2.0 — The Ambient Agent. 14 seconds.
      </p>

      {/* Scroll hint */}
      <div className="absolute bottom-8 left-1/2 -translate-x-1/2 text-slate-600 text-sm animate-bounce select-none">
        ↓
      </div>
    </section>
  );
}
