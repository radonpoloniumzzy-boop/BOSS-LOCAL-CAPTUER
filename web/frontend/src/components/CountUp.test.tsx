import { act, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { CountUp } from "./CountUp";

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

it("shows the final metric immediately when reduced motion is requested", () => {
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true })));

  render(<CountUp to={18103} />);

  expect(screen.getByLabelText("18,103")).toHaveTextContent("18,103");
});

it("reaches the final metric when animation frames are throttled", () => {
  vi.useFakeTimers();
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false })));
  Object.defineProperty(window, "requestAnimationFrame", { configurable: true, value: vi.fn(() => 1) });
  Object.defineProperty(window, "cancelAnimationFrame", { configurable: true, value: vi.fn() });

  render(<CountUp to={158} duration={200} />);
  act(() => vi.advanceTimersByTime(250));

  expect(screen.getByLabelText("158")).toHaveTextContent("158");
});
