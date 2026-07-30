# evo-env-runner

Small std-only JSONL/stdio environment runner. Each non-empty stdin line is a
versioned JSON request object and each request produces one versioned JSON
response object on stdout. The stable process boundary is deliberate: Python
or another host process can supervise it without PyO3 or an in-process ABI.

Prepare an environment:

```json
{"protocol_version":1,"command":"manifest","manifest":{"schema_version":1,"id":"demo","mode":"host","root":"/tmp/demo","workdir":".","argv":["sh","-c","printf hello"],"env":{"LANG":"C"},"outputs":[]}}
```

The response has `{"protocol_version":1,"ok":true,"result":{...},
"attestation":{...}}`; failures have `ok:false` and an `error` object with
`code` and `message`. Then use `inject`, `run`, `collect`, and `destroy` as
JSON objects, for example:

```json
{"protocol_version":1,"command":"run"}
```

`inject` takes an `env` object and merges it into the prepared environment.
`run` returns a structured `result` containing `status`, `code`, `stdout`,
`stderr`, `timed_out`, and `duration_ms`. It executes the manifest argv with a
timeout (default 30 seconds). `collect` reports confined output paths from the
manifest. The runner writes
`.evo-env-attestation.json` inside the confined root.

Python invocation contract (line buffering is the only framing):

```python
import json
import subprocess

proc = subprocess.Popen(
    ["evo-env-runner"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    text=True,
    bufsize=1,
)
proc.stdin.write(json.dumps({"protocol_version": 1, "command": "run"}) + "\n")
proc.stdin.flush()
response = json.loads(proc.stdout.readline())
assert response["protocol_version"] == 1
```

Send one object per line, flush after each request, and read exactly one
response line. Close stdin and wait for the process when the lifecycle is
complete. There is no PyO3 module or shared-memory contract.

Use `mode: "docker"` (or `"docker-argv"`) with an `image` to execute through
Docker. The generated argv includes `--network=none`, `--read-only`,
`--cap-drop=ALL`, `--security-opt=no-new-privileges`, and a PID limit.
