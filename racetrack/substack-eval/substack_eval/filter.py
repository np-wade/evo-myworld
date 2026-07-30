"""Stage 2 — Filter: narrow discovered slugs to the PINNED 60-day window.

The window is [meta.window_start .. meta.ref_date], frozen at fixture time —
the scored path never uses a live now(). Offline set-ops over the dates the
discovery source exposed (archive <time> tags / sitemap <lastmod>):

  passthrough  -- no-op baseline (stage-1 output as-is)
  date-window  -- keep slugs whose source-exposed date is inside the window;
                  slugs with NO date info are DROPPED (a slug we can't date
                  can't be claimed as in-window). SERP output therefore dies
                  here unless combined with per-post fetches — as it should.
  date-window-keep-undated -- lenient variant: undated slugs pass through
                  (recall-greedy, precision-poor on full-history sources).
"""
from __future__ import annotations

from dataclasses import dataclass

from .discover import DiscoverOut


@dataclass
class FilterCandidate:
    key: str
    window: tuple[str, str] | None   # (start, end) ISO days; None=passthrough
    keep_undated: bool = False

    def apply(self, dout: DiscoverOut) -> set[str]:
        if self.window is None:
            return set(dout.slugs)
        lo, hi = self.window
        out = set()
        for s in dout.slugs:
            d = dout.slug_dates.get(s, "")
            if d:
                if lo <= d <= hi:
                    out.add(s)
            elif self.keep_undated:
                out.add(s)
        return out


def build_filters(window_start: str, ref_date: str) -> list[FilterCandidate]:
    w = (window_start, ref_date)
    return [
        FilterCandidate("passthrough", None),
        FilterCandidate("date-window", w),
        FilterCandidate("date-window-keep-undated", w, keep_undated=True),
    ]
