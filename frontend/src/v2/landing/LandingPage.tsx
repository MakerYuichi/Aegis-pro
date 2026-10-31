import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { V2DemoSection } from '../demo/V2DemoSection';
import { usePlayback } from '../demo/usePlayback';
import type { V2Event } from '../types';
import demoEvents from '../demo/demo-investigation.json';
import './landing.css';

const events = demoEvents as V2Event[];

const LINE = 28;
const LINE_COUNT = 320;
const REPO_URL = 'https://github.com/MakerYuichi/Aegis-pro';
const REQUESTS_URL = 'https://github.com/psf/requests';

function findEvent<K extends V2Event['kind']>(kind: K): Extract<V2Event, { kind: K }> | undefined {
  return events.find((e): e is Extract<V2Event, { kind: K }> => e.kind === kind);
}

const clean = (s: string): string => s.replace(/\\\\/g, '\\');

const located   = findEvent('symbol.located');
const hypothesis = findEvent('hypothesis.formed');
const probe      = findEvent('probe.running');
const reproduced = findEvent('probe.reproduced');
const confirmed  = findEvent('bug.confirmed');
const proposed   = findEvent('fix.proposed');
const verified   = findEvent('fix.verified');

const SITE = `${located?.file ?? 'requests/status_codes.py'}:${located?.line ?? 116}`;

const GHOST: string[] = [
  'def _build_lookup_dict():',
  '    codes = _init()',
  "    _codes_str = '\\n'.join([",
  "        '{} ({})'.format(code, ', '.join(titles))",
  '        for code, titles in sorted(_codes.items())',
  '    ])',
  "    __doc__ = (__doc__ + '\\n' + _codes_str)",
  '    codes.__doc__ = __doc__',
  '    return codes',
];
const GHOST_BUG_INDEX = 6;

const FAQS = [
  {
    q: 'Is the investigation above live?',
    a: "No. It is a recording of a real scan of psf/requests, replayed at a pace you can follow. The failure, the error and the verified fix are that scan's output. Streaming a live investigation into this interface is in development.",
  },
  {
    q: 'How is this different from a chat assistant?',
    a: "A chat assistant answers when you ask and can't run its own suggestions. AEGIS PRO starts from the code, reproduces the failure with a probe, and re-runs that probe against its fix before showing it to you.",
  },
  {
    q: 'Can I try it on my own repository?',
    a: 'Yes, with the current v1 pipeline. Paste a public GitHub URL on the demo page.',
  },
  {
    q: 'Where is the source code?',
    a: 'On GitHub at MakerYuichi/Aegis-pro. License terms are in the LICENSE file in that repository.',
  },
];

function DiffBlock({ diff }: { diff: string }) {
  const rows = diff.split('\n').map(clean);
  return (
    <pre className="ap-code">
      {rows.map((row, i) => {
        const sign = row.charAt(0);
        const kind = sign === '+' ? 'add' : sign === '-' ? 'del' : 'ctx';
        const text = kind === 'ctx' ? row : row.slice(1).replace(/^ /, '');
        return (
          <span key={i} className={`ap-diff-row ap-diff-${kind}`}>
            <span className="ap-sign">{kind === 'ctx' ? ' ' : sign}</span>
            <span className="ap-t">{text}</span>
          </span>
        );
      })}
    </pre>
  );
}

function Step({
  tone,
  tag,
  title,
  children,
}: {
  tone: 'amber' | 'red' | 'green';
  tag: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <li className={`ap-step ap-${tone}`} data-lit>
      <span className="ap-tag">{tag}</span>
      <span className="ap-rail" aria-hidden="true" />
      <div className="ap-step-body">
        <h3>{title}</h3>
        {children}
      </div>
    </li>
  );
}

function ArrowGlyph({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size * 1.75} viewBox="0 0 16 28" fill="none" aria-hidden="true">
      <path
        d="M2 14h9M8 9.5l4.5 4.5L8 18.5"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export default function LandingPage() {
  const pageRef = useRef<HTMLDivElement>(null);
  const demoRef = useRef<HTMLElement>(null);
  const startedRef = useRef(false);

  const reducedMotion = useMemo(
    () => typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true,
    [],
  );

  const [ready, setReady] = useState(false);
  const [arrowY, setArrowY] = useState(0);

  const {
    currentIndex,
    isPlaying,
    state: playbackState,
    play,
    pause,
    restart,
    stepForward,
    stepBackward,
    approveFix,
    rejectFix,
  } = usePlayback(events, reducedMotion);

  const gutterLines = useMemo(() => Array.from({ length: LINE_COUNT }, (_, i) => i), []);

  useEffect(() => {
    const id = requestAnimationFrame(() => setReady(true));
    return () => cancelAnimationFrame(id);
  }, []);

  useEffect(() => {
    if (reducedMotion) return;
    const root = document.documentElement;
    const previous = root.style.scrollBehavior;
    root.style.scrollBehavior = 'smooth';
    return () => { root.style.scrollBehavior = previous; };
  }, [reducedMotion]);

  useEffect(() => {
    const page = pageRef.current;
    if (!page) return;
    let frame = 0;

    const measure = () => {
      frame = 0;
      const marks = Array.from(page.querySelectorAll<HTMLElement>('[data-anchor]'));
      if (marks.length === 0) return;
      const pageTop = page.getBoundingClientRect().top;
      const probeLine = window.innerHeight * 0.4;
      let target: HTMLElement | undefined;
      for (const mark of marks) {
        if (!target || mark.getBoundingClientRect().top <= probeLine) target = mark;
      }
      if (!target) return;
      const y = target.getBoundingClientRect().top - pageTop;
      setArrowY(Math.max(0, Math.round(y / LINE) * LINE));
    };

    const schedule = () => { if (!frame) frame = requestAnimationFrame(measure); };

    window.addEventListener('scroll', schedule, { passive: true });
    window.addEventListener('resize', schedule);
    const resizeObserver = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(schedule) : null;
    resizeObserver?.observe(page);
    document.fonts?.ready.then(schedule);
    schedule();

    return () => {
      window.removeEventListener('scroll', schedule);
      window.removeEventListener('resize', schedule);
      resizeObserver?.disconnect();
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);

  useEffect(() => {
    const page = pageRef.current;
    if (!page) return;
    const targets = Array.from(page.querySelectorAll<HTMLElement>('[data-lit]'));
    if (reducedMotion || typeof IntersectionObserver === 'undefined') {
      targets.forEach((el) => el.classList.add('lit'));
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.classList.add('lit');
            observer.unobserve(entry.target);
          }
        }
      },
      { threshold: 0.4 },
    );
    targets.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, [reducedMotion]);

  useEffect(() => {
    if (reducedMotion || typeof IntersectionObserver === 'undefined') return;
    const el = demoRef.current;
    if (!el) return;
    let timer = 0;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry?.isIntersecting || startedRef.current) return;
        observer.disconnect();
        timer = window.setTimeout(() => { startedRef.current = true; play(); }, 1400);
      },
      { threshold: 0.2 },
    );
    observer.observe(el);
    return () => { observer.disconnect(); window.clearTimeout(timer); };
  }, [reducedMotion, play]);

  const replay = useCallback(() => {
    restart();
    window.scrollTo({ top: 0, behavior: reducedMotion ? 'auto' : 'smooth' });
    if (!reducedMotion) window.setTimeout(play, 900);
  }, [restart, play, reducedMotion]);

  return (
    <div ref={pageRef} className={ready ? 'ap ap-ready' : 'ap'}>
      <ol className="ap-gutter" aria-hidden="true">
        {gutterLines.map((i) => (
          <li key={i} className={i * LINE === arrowY ? 'ap-ln on' : 'ap-ln'}>{i + 1}</li>
        ))}
      </ol>
      <div className="ap-band" style={{ transform: `translateY(${arrowY}px)` }} aria-hidden="true" />
      <div className="ap-arrow" style={{ transform: `translateY(${arrowY}px)` }} aria-hidden="true">
        <span key={arrowY} className="ap-pulse" />
        <ArrowGlyph />
      </div>

      <header className="ap-nav">
        <div className="ap-wrap ap-nav-in">
          <a className="ap-brand" href="#top">
            <ArrowGlyph size={12} />
            AEGIS PRO
          </a>
          <nav className="ap-links" aria-label="Page sections">
            <a href="#process">Process</a>
            <a href="#proof">Proof</a>
            <a href="#status">Status</a>
            <a href="#faq">FAQ</a>
            <a href={REPO_URL} target="_blank" rel="noopener noreferrer">GitHub</a>
          </nav>
          <Link className="ap-btn ap-btn-solid ap-btn-sm" to="/demo">Open the demo</Link>
        </div>
      </header>

      <main className="ap-main">
        <section id="top" className="ap-hero">
          <div className="ap-wrap ap-rel">
            <div className="ap-ghost" aria-hidden="true">
              {GHOST.map((line, i) => (
                <div key={i} className={i === GHOST_BUG_INDEX ? 'ap-ghost-line bug' : 'ap-ghost-line'}>{line}</div>
              ))}
            </div>

            <h1 className="ap-title">
              <span className="ap-hl"><span>Watch the bug</span></span>
              <span className="ap-hl" data-anchor="top"><span>get found.</span></span>
            </h1>

            <div className="ap-hero-row">
              <p className="ap-lead ap-intro ap-d1">
                AEGIS PRO reads your code, reproduces the crash with a real probe, then checks its own fix against
                that probe. Below is a recorded run on a real bug in psf/requests.
              </p>
              <div className="ap-actions ap-intro ap-d2">
                <Link className="ap-btn ap-btn-solid" to="/demo">Analyze a public repo</Link>
                <a className="ap-btn ap-btn-line" href={REPO_URL} target="_blank" rel="noopener noreferrer">Read the source</a>
              </div>
            </div>

            <div className="ap-frame ap-intro ap-d3">
              <div className="ap-frame-bar">
                <span>{SITE.split(':')[0]}</span>
                <span>Recorded replay of incident INC-20261029-A42D5F</span>
              </div>
              <V2DemoSection
                ref={demoRef}
                events={events}
                currentIndex={currentIndex}
                isPlaying={isPlaying}
                playbackState={playbackState}
                reducedMotion={reducedMotion}
                onPlay={play}
                onPause={pause}
                onRestart={restart}
                onStepForward={stepForward}
                onStepBackward={stepBackward}
                onApproveFix={approveFix}
                onRejectFix={rejectFix}
              />
            </div>
          </div>
        </section>

        <section id="process" className="ap-sec">
          <div className="ap-wrap">
            <span className="ap-mark" data-anchor="process" />
            <div className="ap-split">
              <div className="ap-sticky">
                <h2 className="ap-h2">From suspicion to proof</h2>
                <p className="ap-lead">These are the four stages of the replay above. The text and code here are read from the same recording.</p>
              </div>
              <ol className="ap-trace">
                <Step tone="amber" tag="suspect" title="It names a specific failure mode.">
                  <p>{clean(hypothesis?.text ?? '')}</p>
                  <pre className="ap-code">
                    <code>
                      <span className="dim">{SITE}</span>
                      {'\n'}{`__doc__ = (__doc__ + '\\n' + _codes_str)`}
                    </code>
                  </pre>
                </Step>
                <Step tone="red" tag="reproduce" title="It reproduces the crash.">
                  <p>A probe runs the crash site with the flags that trigger it, instead of trusting a reading of the code.</p>
                  <pre className="ap-code">
                    <code>
                      <span className="dim">probe flags: {probe?.flags.join(' ') ?? ''}</span>
                      {'\n'}
                      <span className="err">{reproduced?.error ?? ''}</span>
                    </code>
                  </pre>
                </Step>
                <Step tone="green" tag="fix" title="It proposes a fix.">
                  <p>Confirmed: {clean(confirmed?.failure_mode ?? '')}.</p>
                  <DiffBlock diff={proposed?.diff ?? ''} />
                </Step>
                <Step tone="green" tag="verify" title="It re-runs the probe against the fix.">
                  <p>{clean(verified?.output ?? '')} Nothing is applied until you approve it.</p>
                </Step>
              </ol>
            </div>
          </div>
        </section>

        <section id="proof" className="ap-sec">
          <div className="ap-wrap">
            <span className="ap-mark" data-anchor="proof" />
            <div className="ap-split">
              <div>
                <h2 className="ap-h2">Review bots guess. This one runs the code.</h2>
                <p className="ap-lead">Linters check style and review bots comment on diffs. Neither can tell you whether the code actually fails. AEGIS PRO reproduces the failure first.</p>
              </div>
              <dl className="ap-rules">
                <div className="ap-rule"><dt>Reproduce first</dt><dd>The failing code path runs before any fix is written. If it can&apos;t be reproduced, the finding is labeled unverified.</dd></div>
                <div className="ap-rule"><dt>Verify after</dt><dd>The same probe runs against the proposed fix, so you see it fail before and pass after.</dd></div>
                <div className="ap-rule"><dt>Show the work</dt><dd>Every step appears in the editor as it happens, attached to the line it concerns.</dd></div>
                <div className="ap-rule"><dt>You approve</dt><dd>Fixes are staged for review. Nothing is merged automatically.</dd></div>
              </dl>
            </div>
          </div>
        </section>

        <section id="status" className="ap-sec">
          <div className="ap-wrap">
            <span className="ap-mark" data-anchor="status" />
            <h2 className="ap-h2">What you can use today</h2>
            <div className="ap-pair">
              <article className="ap-panel">
                <p className="ap-state"><i />available now</p>
                <h3>Analyze a public repo</h3>
                <p>Paste a GitHub URL. AEGIS PRO picks a file, finds a likely production risk, and returns an incident with the failing line, the surrounding code, who changed it, related changes and a suggested fix.</p>
                <Link className="ap-btn ap-btn-solid" to="/demo">Open the demo</Link>
              </article>
              <article className="ap-panel soon">
                <p className="ap-state"><i />in development</p>
                <h3>The live editor</h3>
                <p>The interface you watched above, fed by a live investigation instead of a recording. The recording uses the same event format a live stream will, so the interface stays as it is.</p>
                <a className="ap-btn ap-btn-line" href={REPO_URL} target="_blank" rel="noopener noreferrer">Follow the work on GitHub</a>
              </article>
            </div>
          </div>
        </section>

        <section id="faq" className="ap-sec">
          <div className="ap-wrap">
            <span className="ap-mark" data-anchor="faq" />
            <div className="ap-split">
              <h2 className="ap-h2">Questions</h2>
              <div className="ap-faq">
                {FAQS.map((f) => (
                  <details key={f.q}>
                    <summary>{f.q}</summary>
                    <p>{f.a}</p>
                  </details>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section id="start" className="ap-sec ap-start">
          <div className="ap-wrap">
            <span className="ap-mark" data-anchor="start" />
            <h2 className="ap-start-title">Point it at a repo.</h2>
            <p className="ap-lead">Paste a public GitHub URL and get an incident with the failing line, the blame and a suggested fix.</p>
            <div className="ap-actions ap-actions-start">
              <Link className="ap-btn ap-btn-solid" to="/demo">Analyze a public repo</Link>
              <button type="button" className="ap-btn ap-btn-line" onClick={replay}>Replay the investigation</button>
            </div>
          </div>
        </section>
      </main>

      <footer className="ap-foot">
        <div className="ap-wrap ap-foot-in">
          <p>AEGIS PRO. The investigation on this page is a replay of a real scan of{' '}
            <a className="ap-ulink" href={REQUESTS_URL} target="_blank" rel="noopener noreferrer">psf/requests</a>.
          </p>
          <nav aria-label="Footer">
            <Link to="/demo">Demo</Link>
            <a href={REPO_URL} target="_blank" rel="noopener noreferrer">GitHub</a>
          </nav>
        </div>
      </footer>
    </div>
  );
}
