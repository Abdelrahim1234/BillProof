"use client";

import { useEffect, useState } from "react";
import { formatMoney, type LineComparison, type Money } from "@/lib/api";

/**
 * Paired bars: what the bill asked for, against what the hospital publishes.
 *
 * Two measures of the same kind on one shared scale, so bar lengths are
 * comparable both within a line and across every line on the wall. Two steps of
 * a single hue (never two categorical hues, because these are not different
 * categories, they are the same quantity measured twice), validated against the
 * light chart surface with the palette validator.
 *
 * The bars are aria-hidden: every value they encode is already printed beside
 * them as text, so a screen reader would otherwise read the bill twice.
 */

export const SERIES = {
  charged: "#14532d",
  published: "#5fa87c",
} as const;

/** The largest amount anywhere on screen, so every bar shares one axis. */
export function scaleFor(comparisons: LineComparison[]): number {
  let max = 0;
  for (const c of comparisons) {
    max = Math.max(max, c.comparison_subject?.money.amount_cents ?? 0);
    max = Math.max(max, c.benchmark?.median?.amount_cents ?? 0);
  }
  return max || 1;
}

function Bar({
  cents,
  scale,
  color,
  delay = 0,
}: {
  cents: number;
  scale: number;
  color: string;
  delay?: number;
}) {
  const pct = Math.max(0.6, (cents / scale) * 100);
  // Start at zero, then hand the real width to CSS on the next frame so the
  // transition has something to animate from. The easing decelerates, so a bar
  // rushes out and settles onto its value rather than sliding at a constant
  // rate. Motion is disabled wholesale under prefers-reduced-motion.
  const [grown, setGrown] = useState(false);
  useEffect(() => {
    const id = requestAnimationFrame(() => setGrown(true));
    return () => cancelAnimationFrame(id);
  }, []);

  return (
    <div className="bar-track">
      <div
        className="bar-fill"
        style={{
          width: grown ? `${pct}%` : "0%",
          background: color,
          transitionDelay: `${delay}ms`,
        }}
      />
    </div>
  );
}

export function PairedBars({
  charged,
  published,
  scale,
  chargedLabel,
  publishedLabel,
}: {
  charged: Money | null | undefined;
  published: Money | null | undefined;
  scale: number;
  chargedLabel: string;
  publishedLabel: string;
}) {
  if (!charged || !published) return null;
  return (
    <div className="bars" aria-hidden="true">
      <div className="bar-row">
        <span className="bar-key">{chargedLabel}</span>
        <Bar cents={charged.amount_cents} scale={scale} color={SERIES.charged} />
        <span className="bar-value">{formatMoney(charged)}</span>
      </div>
      <div className="bar-row">
        <span className="bar-key">{publishedLabel}</span>
        <Bar cents={published.amount_cents} scale={scale} color={SERIES.published} delay={90} />
        <span className="bar-value">{formatMoney(published)}</span>
      </div>
    </div>
  );
}

/** Two series are on screen, so a legend is always present. */
export function BarsLegend() {
  return (
    <p className="bars-legend">
      <span className="swatch" style={{ background: SERIES.charged }} aria-hidden="true" />
      On the bill
      <span className="swatch" style={{ background: SERIES.published }} aria-hidden="true" />
      Published by the hospital
    </p>
  );
}
