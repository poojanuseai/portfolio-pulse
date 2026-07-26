"""One heartbeat per ~10-minute tick — currently just runs fast_poll.

Kept as its own module (rather than having the workflow call fast_poll
directly) so a future once-a-day job — e.g. an end-of-day-only pass, once
custom alert criteria (signals/criteria.py) are defined and some of them turn
out to be daily rather than every-tick — has an obvious, already-wired place
to gate on time-of-day, the same way the original template gated its daily
DMA scan here.
"""

from __future__ import annotations

from portfolio_pulse.jobs import fast_poll


def run() -> dict:
    return {"fast_poll": fast_poll.run()}


if __name__ == "__main__":
    print(run())
