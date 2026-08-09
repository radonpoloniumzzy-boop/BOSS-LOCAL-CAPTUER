import { useEffect, useState } from "react";

type CountUpProps = {
  to: number;
  from?: number;
  duration?: number;
  prefix?: string;
};

const format = (value: number, prefix: string) =>
  `${prefix}${Math.round(value).toLocaleString("zh-CN")}`;

function shouldReduceMotion() {
  return typeof window === "undefined"
    || typeof window.matchMedia !== "function"
    || window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

// Adapted from the React Bits CountUp pattern without its motion runtime dependency.
export function CountUp({ to, from = 0, duration = 650, prefix = "" }: CountUpProps) {
  const [value, setValue] = useState(() => shouldReduceMotion() ? to : from);

  useEffect(() => {
    if (shouldReduceMotion() || duration <= 0 || from === to) {
      setValue(to);
      return;
    }

    let frame = 0;
    const requestFrame = typeof window.requestAnimationFrame === "function"
      ? window.requestAnimationFrame.bind(window)
      : (callback: FrameRequestCallback) => window.setTimeout(() => callback(performance.now()), 16);
    const cancelFrame = typeof window.cancelAnimationFrame === "function"
      ? window.cancelAnimationFrame.bind(window)
      : window.clearTimeout.bind(window);
    const startedAt = performance.now();
    const tick = (now: number) => {
      const progress = Math.min((now - startedAt) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setValue(from + (to - from) * eased);
      if (progress < 1) frame = requestFrame(tick);
    };
    frame = requestFrame(tick);
    const fallback = window.setTimeout(() => setValue(to), duration + 50);
    return () => {
      cancelFrame(frame);
      window.clearTimeout(fallback);
    };
  }, [duration, from, to]);

  const finalLabel = format(to, prefix);
  return (
    <span aria-label={finalLabel}>
      <span aria-hidden="true">{format(value, prefix)}</span>
    </span>
  );
}
