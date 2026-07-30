# Sources and provenance

This crate is new evo-hq code and has no third-party Rust dependencies.

The following local Apache-2.0 ports were inspected for compatible patterns:

- `/home/npwad/coding/docker-envs/projects/_ports/docker-isolation`
  - Docker isolation argv construction and Docker image, environment-key, and
    environment-value validation patterns.
  - The port identifies its upstream as TakoVM and records Apache-2.0
    provenance in its own `SOURCES.md`.
- `/home/npwad/coding/docker-envs/projects/_ports/docker-triage`
  - std `Command` execution with piped stdout/stderr, polling, and timeout
    cleanup.
  - The port identifies its upstream as TakoVM and records Apache-2.0
    provenance in its own `SOURCES.md`.
- `/home/npwad/coding/docker-envs/projects/_ports/spawn-hardened`
  - Reviewed only for process-spawn hygiene. Its OpenShell-derived privileged
    Linux hardening code is not copied here because this runner is std-only and
    must remain portable without adding `libc`, `rustix`, or `capctl`.

The requested local `event-pipe` source directory was not present under
`/home/npwad/coding/docker-envs/projects` at implementation time, so no code
was taken from it.

The runner uses direct argv execution and does not copy shell command parsing,
container lifecycle code, or security profiles from those ports. The Docker
mode adds `--network=none` by default and never constructs a shell command.
