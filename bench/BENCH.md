# The Bench — a small place to experiment on code

Not a judge. Not a harness. Just a bench: run **two versions of the same
thing** and look at the difference — outputs, behaviour, timing. That's
the whole loop the lab is built on (evo does it at scale; this is the
hand tool). Use it to see if a change actually does anything before you
believe it does.

## Run two things and compare

```
bench/experiment.sh "<command A>" "<command B>"
```

Runs both, captures stdout + exit + wall-time, prints them side by side
and a unified diff of their outputs. A = the original/baseline, B = your
version. If the diff is empty, your change changed nothing observable —
worth knowing.

## Look at part of a codebase's functions

```
bench/experiment.sh --funcs <file.py|file.rs>
```

Lists the functions/signatures in one file so you can see the surface
you're about to experiment on, without reading the whole thing.

## Optional: leave a repeatable experiment next to your work

Drop `world/<seat>/experiment.env` if you want the lab loop to re-run
your comparison each cycle and keep a short trail:

```sh
BASE_CMD="the original behaviour"       # run this
NEW_CMD="your version's behaviour"      # and this
NOTE="one line: what you're checking"
```

The loop runs `experiment.sh "$BASE_CMD" "$NEW_CMD"` and appends a
one-line result to `bench/trail.md` (date · seat · same/different ·
timings). No pass/fail ceremony — just a record of what happened, so you
can watch a thing get better (or not) across cycles.

Small only: seconds not minutes, tiny inputs — this is a 12GB box.
