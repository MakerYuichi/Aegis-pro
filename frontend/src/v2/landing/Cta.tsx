export function Cta() {
  const scrollToTop = () => {
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  return (
    <section
      className="min-h-screen bg-slate-950 flex flex-col items-center justify-center px-4 text-center"
      style={{ minHeight: '100vh' }}
    >
      <h2 className="text-4xl md:text-5xl font-bold tracking-tight text-white leading-tight max-w-3xl">
        This is v2.0. The future of the pipeline you already have.
      </h2>

      <p className="text-lg text-slate-400 mt-8 max-w-2xl leading-relaxed">
        AEGIS PRO v1.0 shipped and is live in production. V2.0 is the next chapter —
        autonomous investigation, ambient agents, every finding visible. You already have
        the pipeline. This is what it becomes.
      </p>

      <button
        onClick={scrollToTop}
        className="mt-10 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 font-semibold px-8 py-4 rounded-lg text-lg cursor-pointer transition-colors duration-200"
      >
        Back to the top
      </button>
    </section>
  );
}
