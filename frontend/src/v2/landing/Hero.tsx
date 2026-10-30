interface HeroProps {
  onWatchItWork: () => void;
}

export function Hero({ onWatchItWork }: HeroProps) {
  return (
    <section
      className="min-h-screen bg-slate-950 flex flex-col items-center justify-center px-4 text-center"
      style={{ minHeight: '100vh' }}
    >
      <h1 className="text-6xl md:text-7xl font-bold tracking-tight text-white leading-tight">
        Watch the bug get found.
      </h1>

      <p className="text-xl md:text-2xl text-slate-400 mt-6 max-w-2xl leading-relaxed">
        AEGIS PRO investigates your code, live. Every arrow, every callout, every fix — visible.
      </p>

      <button
        onClick={onWatchItWork}
        className="bg-blue-600 hover:bg-blue-500 text-white font-semibold px-8 py-4 rounded-lg text-lg mt-10 cursor-pointer transition-colors duration-200"
      >
        ▶ Watch it work
      </button>

      {/* Scroll hint */}
      <div className="absolute bottom-8 left-1/2 -translate-x-1/2 text-slate-600 text-sm animate-bounce select-none">
        ↓
      </div>
    </section>
  );
}
