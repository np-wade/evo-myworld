"""ip_eval — Information Processer racetrack suite.

Self-authored-oracle benchmark for the 8-stage document pipeline described in
information-processer/RACETRACK_EXHAUSTIVE_TEST_REPOSITORY_MATRIX.md.

Design rules (bench-factory, locked 2026-07-25/26):
- grader owns the truth: fixtures are generated with a seeded RNG and gold is
  recorded at generation time; candidates never see fixtures/gold.json.
- two-track scoring: machinery hard-scored vs gold; judgment advisory-only.
- no LLM judge in the hard path; offline-rerunnable; available()-gated deps.
"""

__version__ = "0.1.0"
