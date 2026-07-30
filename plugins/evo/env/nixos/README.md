# Evo disposable Nix environment

This flake supplies the same base tools to Python and Rust test adapters. The
runner should build/cache the closure once, create a disposable workspace for
each experiment, inject the candidate and fixtures, and record the flake lock
and resulting environment digest in the evidence envelope.

The `nixosConfigurations.evo-test` profile is intentionally container-friendly
for fast CI/local execution. Full kernel-isolated NixOS confirmation can use the
same locked inputs through a microVM provider.
