export function AboutDemo() {
  return (
    <section className="py-16 bg-aegis-bg px-4 border-t border-aegis-line">
      <div className="max-w-2xl mx-auto">
        <h2 className="text-lg font-semibold text-slate-300 mb-3">About this demo</h2>
        <p className="text-slate-400 leading-relaxed text-sm">
          This is a recorded replay of a real AEGIS PRO investigation: incident{' '}
          <code className="font-mono text-xs bg-aegis-line px-1 py-0.5 rounded">INC-20261029-A42D5F</code>,
          a scan of{' '}
          <a
            href="https://github.com/psf/requests"
            target="_blank"
            rel="noopener noreferrer"
            className="text-slate-300 underline underline-offset-2 hover:text-slate-100"
          >
            psf/requests
          </a>
          . AEGIS found that <code className="font-mono text-xs">__doc__</code> at{' '}
          <code className="font-mono text-xs">requests/status_codes.py:116</code> raises{' '}
          <code className="font-mono text-xs">TypeError</code> under{' '}
          <code className="font-mono text-xs">python -OO</code>, reproduced the crash, generated
          the guard, and verified the fix.
        </p>
        <p className="text-slate-500 text-sm mt-4">
          The investigation you watched is real.{' '}
          <a
            href="https://github.com/MakerYuichi/Aegis-pro"
            target="_blank"
            rel="noopener noreferrer"
            className="text-slate-400 underline underline-offset-2 hover:text-slate-300"
          >
            View AEGIS PRO on GitHub →
          </a>
        </p>
      </div>
    </section>
  );
}
