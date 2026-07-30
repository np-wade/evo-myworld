// ip_store_driver.mjs — persistence probes against the incumbent's store.
// Usage: node ip_store_driver.mjs <action>   (JSON on stdin, JSON on stdout)
// Actions: write_read | concurrent | corrupt_read | atomicity | safe_name
import { writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const serverDir = resolve(
  process.env.IP_SERVER_DIR
    ?? new URL('../../../../information-processer/server', import.meta.url).pathname,
);
const store = await import(new URL(`file://${serverDir}/store.mjs`));
const tools = await import(new URL(`file://${serverDir}/tools.mjs`));

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}');
}

const action = process.argv[2];
const req = await readStdin();
const workspaceFile = resolve(store.dataDirectory, 'workspace.json');

function makeWorkspace(tag, n) {
  return {
    documents: Array.from({ length: n }, (_, i) => ({
      id: `doc-${tag}-${i}`, name: `Document ${tag} ${i}`, content: `body ${tag} ${i}`,
    })),
  };
}

async function run() {
  switch (action) {
    case 'write_read': {
      const n = req.n ?? 50;
      const docsPerWrite = req.docsPerWrite ?? 40;
      const timings = [];
      for (let i = 0; i < n; i += 1) {
        const started = performance.now();
        await store.writeWorkspace(makeWorkspace(i, docsPerWrite));
        timings.push(performance.now() - started);
      }
      timings.sort((a, b) => a - b);
      const readBack = await store.readWorkspace();
      return {
        ok: true,
        p50_ms: timings[Math.floor(timings.length / 2)],
        p95_ms: timings[Math.floor(timings.length * 0.95)],
        documents: readBack.documents.length,
      };
    }
    case 'concurrent': {
      // two "writers" interleave read-modify-write through updateWorkspace;
      // every record must survive (no lost updates)
      const writers = req.writers ?? ['A', 'B'];
      const opsPerWriter = req.ops ?? 20;
      await store.writeWorkspace(makeWorkspace('seed', 0));
      await Promise.all(writers.map((tag) => (async () => {
        for (let i = 0; i < opsPerWriter; i += 1) {
          await store.updateWorkspace((workspace) => {
            workspace.documents = [
              ...(workspace.documents ?? []),
              { id: `doc-${tag}-${i}`, name: `${tag}${i}` },
            ];
          });
        }
      })()));
      const final = await store.readWorkspace();
      const expected = writers.length * opsPerWriter;
      const present = new Set((final.documents ?? []).map((d) => d.id));
      let surviving = 0;
      for (const tag of writers) {
        for (let i = 0; i < opsPerWriter; i += 1) {
          if (present.has(`doc-${tag}-${i}`)) surviving += 1;
        }
      }
      return { ok: true, expected, surviving, lost: expected - surviving };
    }
    case 'atomicity': {
      // tight write loop with a concurrent reader; a torn read = unparseable
      const writes = req.writes ?? 150;
      let torn = 0;
      let stopped = false;
      const reader = (async () => {
        const { readFile } = await import('node:fs/promises');
        while (!stopped) {
          try {
            JSON.parse(await readFile(workspaceFile, 'utf8'));
          } catch (error) {
            if (error.code !== 'ENOENT') torn += 1;
          }
        }
      })();
      for (let i = 0; i < writes; i += 1) {
        await store.writeWorkspace(makeWorkspace(i, 5));
      }
      stopped = true;
      await reader;
      return { ok: true, torn_reads: torn, writes };
    }
    case 'corrupt_read': {
      await writeFile(workspaceFile, '{"version": 1, "documents": [TRUNCATED', 'utf8');
      try {
        await store.readWorkspace();
        return { ok: true, behavior: 'recovered-default' };
      } catch (error) {
        return { ok: true, behavior: `threw:${error.constructor.name}` };
      }
    }
    case 'safe_name': {
      const inputs = req.inputs ?? [];
      return {
        ok: true,
        results: inputs.map((value) => ({
          input: value,
          output: tools.safeUploadName(value),
        })),
      };
    }
    default:
      return { ok: false, error: `unknown action: ${action}` };
  }
}

try {
  const result = await run();
  process.stdout.write(JSON.stringify(result));
} catch (error) {
  process.stdout.write(JSON.stringify({ ok: false, error: String(error?.message ?? error) }));
  process.exitCode = 3;
}
