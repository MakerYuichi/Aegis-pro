import { useState, useEffect, useCallback, useRef } from 'react';
import type { V2Event, PlaybackState } from '../types';

export function usePlayback(events: V2Event[]): {
  currentIndex: number;
  isPlaying: boolean;
  state: PlaybackState;
  play: () => void;
  pause: () => void;
  restart: () => void;
  stepForward: () => void;
  stepBackward: () => void;
  approveFix: () => void;
  rejectFix: () => void;
} {
  const [currentIndex, setCurrentIndex] = useState(-1);
  const [playbackState, setPlaybackState] = useState<PlaybackState>('idle');
  const approveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Keep refs for use inside callbacks/effects without stale closures
  const playbackStateRef = useRef<PlaybackState>('idle');
  playbackStateRef.current = playbackState;

  const isPlaying = playbackState === 'playing';

  const play = useCallback(() => {
    setPlaybackState((s) => {
      if (s === 'idle' || s === 'paused') return 'playing';
      return s;
    });
  }, []);

  const pause = useCallback(() => {
    setPlaybackState((s) => (s === 'playing' ? 'paused' : s));
  }, []);

  const restart = useCallback(() => {
    if (approveTimerRef.current) {
      clearTimeout(approveTimerRef.current);
      approveTimerRef.current = null;
    }
    setCurrentIndex(-1);
    setPlaybackState('idle');
  }, []);

  const stepForward = useCallback(() => {
    const s = playbackStateRef.current;
    if (s === 'awaiting-approval' || s === 'applying') return;
    setCurrentIndex((i) => Math.min(i + 1, events.length - 1));
  }, [events.length]);

  const stepBackward = useCallback(() => {
    const s = playbackStateRef.current;
    if (s === 'awaiting-approval' || s === 'applying') return;
    setCurrentIndex((i) => Math.max(i - 1, -1));
  }, []);

  const approveFix = useCallback(() => {
    if (playbackStateRef.current !== 'awaiting-approval') return;
    setPlaybackState('applying');
    approveTimerRef.current = setTimeout(() => {
      // Advance past fix.proposed to next event (fix.verified)
      setCurrentIndex((i) => Math.min(i + 1, events.length - 1));
      setPlaybackState('playing');
    }, 1500);
  }, [events.length]);

  const rejectFix = useCallback(() => {
    if (playbackStateRef.current !== 'awaiting-approval') return;
    setPlaybackState('rejected');
  }, []);

  // Auto-advance timer — runs only when state === 'playing'
  useEffect(() => {
    if (playbackState !== 'playing') return;
    if (currentIndex >= events.length - 1) {
      setPlaybackState('paused');
      return;
    }

    const nextIndex = currentIndex + 1;
    const nextEvent = events[nextIndex];

    // If the next event to dispatch is fix.proposed, advance to it and stop for approval
    if (nextEvent && nextEvent.kind === 'fix.proposed') {
      const id = setTimeout(() => {
        setCurrentIndex(nextIndex);
        setPlaybackState('awaiting-approval');
      }, 1500);
      return () => clearTimeout(id);
    }

    const id = setTimeout(() => {
      setCurrentIndex((i) => i + 1);
    }, 1500);
    return () => clearTimeout(id);
  }, [playbackState, currentIndex, events]);

  // Detect investigation.complete → state becomes verified
  useEffect(() => {
    if (currentIndex < 0) return;
    const event = events[currentIndex];
    if (event && event.kind === 'investigation.complete') {
      setPlaybackState('verified');
    }
  }, [currentIndex, events]);

  // Cleanup approve timer on unmount
  useEffect(() => {
    return () => {
      if (approveTimerRef.current) clearTimeout(approveTimerRef.current);
    };
  }, []);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const s = playbackStateRef.current;
      if (e.key === ' ') {
        e.preventDefault();
        if (s === 'playing') {
          setPlaybackState('paused');
        } else if (s === 'idle' || s === 'paused') {
          setPlaybackState('playing');
        }
      }
      if (e.key === 'Escape') {
        if (approveTimerRef.current) {
          clearTimeout(approveTimerRef.current);
          approveTimerRef.current = null;
        }
        setCurrentIndex(-1);
        setPlaybackState('idle');
      }
      if (e.key === 'ArrowRight') {
        e.preventDefault();
        const cs = playbackStateRef.current;
        if (cs === 'awaiting-approval' || cs === 'applying') return;
        setCurrentIndex((i) => Math.min(i + 1, events.length - 1));
      }
      if (e.key === 'ArrowLeft') {
        e.preventDefault();
        const cs = playbackStateRef.current;
        if (cs === 'awaiting-approval' || cs === 'applying') return;
        setCurrentIndex((i) => Math.max(i - 1, -1));
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [events.length]);

  return {
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
  };
}
