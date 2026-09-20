# Frontend UI review log

Running notes from the 5-minute review loop. Changes here are local only —
deploying stays a manual step.

## 2026-09-19 — Run 1: phone start screen + sample picker

Changed:
- Moved **Check my own bill** above the "More examples" disclosure. With nine
  samples expanded, the second way into the app was pushed nearly a full screen
  down; the two entry points now sit together and the example list opens below
  both.
- Gave the examples toggle a 44px tap target (`button.link.expander`). It was
  35px, the only control on the screen under the threshold.

Left alone, deliberately:
- The nine-item example list is long, but each entry earns its place by showing
  a different outcome, and the disclosure keeps it out of the way by default.
- Headline and fineprint wording: it follows docs/01-product-truth.md and is not
  mine to reword casually.
- Per-sample "what this shows" badges were considered and rejected: the blurb
  already says it, and a badge would compete with the review-label tags that
  carry real meaning later in the flow.

Note for later runs: `next build` replaces `.next` under a running `next start`,
which makes the preview serve 404ing JS chunks and silently breaks hydration.
Always restart the :3100 preview after a build before screenshotting.
