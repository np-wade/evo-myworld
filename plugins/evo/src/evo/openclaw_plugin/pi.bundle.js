// ../opencode_plugin/drain.ts
import * as fs from "fs";
import * as path from "path";
var QUEUE_SCHEMA_VERSION = 1;
function injectRoot(runDir) {
  return path.join(runDir, "inject");
}
function sessionFile(runDir, sid) {
  return path.join(injectRoot(runDir), "sessions", `${sid}.json`);
}
function workspaceEventsPath(runDir) {
  return path.join(injectRoot(runDir), "events", "workspace.jsonl");
}
function expEventsPath(runDir, expId) {
  return path.join(injectRoot(runDir), "events", `${expId}.jsonl`);
}
function offsetFile(runDir, sid) {
  return path.join(injectRoot(runDir), "offsets", `${sid}.json`);
}
function markerFile(runDir, sid) {
  return path.join(injectRoot(runDir), "markers", `${sid}.flag`);
}
function readJsonOrNull(p) {
  try {
    return JSON.parse(fs.readFileSync(p, "utf8"));
  } catch {
    return null;
  }
}
function atomicWriteJson(p, data) {
  fs.mkdirSync(path.dirname(p), { recursive: true });
  const tmp = `${p}.tmp.${process.pid}`;
  fs.writeFileSync(tmp, JSON.stringify(data));
  fs.renameSync(tmp, p);
}
function unlinkIfExists(p) {
  try {
    fs.unlinkSync(p);
  } catch {}
}
function readEventsAfter(queuePath, afterId) {
  if (!fs.existsSync(queuePath))
    return [];
  let text;
  try {
    text = fs.readFileSync(queuePath, "utf8");
  } catch {
    return [];
  }
  const out = [];
  for (const line of text.split(`
`)) {
    const trimmed = line.trim();
    if (!trimmed)
      continue;
    let rec;
    try {
      rec = JSON.parse(trimmed);
    } catch {
      continue;
    }
    const recId = rec?.id;
    if (typeof recId !== "string")
      continue;
    if (afterId === null || recId > afterId) {
      out.push(rec);
    }
  }
  return out;
}
function readOffset(runDir, sid, queue) {
  const data = readJsonOrNull(offsetFile(runDir, sid));
  if (!data)
    return null;
  if (queue === "workspace")
    return data.last_workspace_event_id ?? null;
  if (queue === "exp")
    return data.last_exp_event_id ?? null;
  return null;
}
function nowIso() {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "+00:00");
}
function writeOffset(runDir, sid, opts) {
  const p = offsetFile(runDir, sid);
  let data = readJsonOrNull(p) ?? {};
  data.schema_version = QUEUE_SCHEMA_VERSION;
  data.session_id = sid;
  if (opts.workspaceId !== undefined && opts.workspaceId !== null) {
    data.last_workspace_event_id = opts.workspaceId;
  }
  if (opts.expId !== undefined && opts.expId !== null) {
    data.last_exp_event_id = opts.expId;
  }
  data.updated_at = nowIso();
  atomicWriteJson(p, data);
}
function formatDirectiveText(events) {
  const lines = [];
  for (const ev of events) {
    if (!ev.text)
      continue;
    const id = ev.id || "";
    if (id) {
      lines.push(`[EVO DIRECTIVE id=${id}]`);
      lines.push(ev.text);
      lines.push(`[END EVO DIRECTIVE — when done, run: evo ack ${id}]`);
    } else {
      lines.push("[EVO DIRECTIVE]");
      lines.push(ev.text);
      lines.push("[END EVO DIRECTIVE]");
    }
  }
  return lines.join(`
`);
}
function getSession(runDir, sid) {
  return readJsonOrNull(sessionFile(runDir, sid));
}
function isRegistered(runDir, sid) {
  return fs.existsSync(sessionFile(runDir, sid));
}
var REGISTRY_SCHEMA_VERSION = 1;
function registerSession(runDir, sid, host, expId = null) {
  const p = sessionFile(runDir, sid);
  const now = nowIso();
  const existing = readJsonOrNull(p);
  if (existing) {
    existing.last_seen_at = now;
    if (expId && !existing.exp_id)
      existing.exp_id = expId;
    if (existing.has_evo_engaged === undefined)
      existing.has_evo_engaged = false;
    if (existing.engaged_at === undefined)
      existing.engaged_at = null;
    atomicWriteJson(p, existing);
    return;
  }
  const rec = {
    schema_version: REGISTRY_SCHEMA_VERSION,
    session_id: sid,
    host,
    pid: process.pid,
    registered_at: now,
    last_seen_at: now,
    exp_id: expId,
    parent_session_id: null,
    has_evo_engaged: false,
    engaged_at: null
  };
  atomicWriteJson(p, rec);
  initOffsetToLatest(runDir, sid);
}
function markEngaged(runDir, sid) {
  const p = sessionFile(runDir, sid);
  const rec = readJsonOrNull(p);
  if (!rec)
    return false;
  if (rec.has_evo_engaged)
    return false;
  rec.has_evo_engaged = true;
  rec.engaged_at = nowIso();
  atomicWriteJson(p, rec);
  return true;
}
function initOffsetToLatest(runDir, sid) {
  const wsPath = workspaceEventsPath(runDir);
  let latest = null;
  if (fs.existsSync(wsPath)) {
    const events = readEventsAfter(wsPath, null);
    if (events.length > 0)
      latest = events[events.length - 1].id;
  }
  writeOffset(runDir, sid, { workspaceId: latest });
}
var EVO_CMD_RE = /^\s*evo(\s|$)/;
function isEvoCommand(command) {
  if (!command || typeof command !== "string")
    return false;
  return EVO_CMD_RE.test(command);
}
function findEvoRunDir(cwd) {
  const envRunDir = process.env.EVO_RUN_DIR;
  if (envRunDir)
    return envRunDir;
  let dir = cwd || process.cwd();
  while (dir !== "/" && dir !== "") {
    const evoDir = path.join(dir, ".evo");
    if (fs.existsSync(evoDir)) {
      try {
        const runs = fs.readdirSync(evoDir).filter((n) => n.startsWith("run_")).sort();
        if (runs.length === 0)
          return null;
        return path.join(evoDir, runs[runs.length - 1]);
      } catch {
        return null;
      }
    }
    const parent = path.dirname(dir);
    if (parent === dir)
      break;
    dir = parent;
  }
  return null;
}
function drainSession(runDir, sessionId) {
  const sess = getSession(runDir, sessionId);
  if (!sess) {
    unlinkIfExists(markerFile(runDir, sessionId));
    return { text: null, newWorkspaceOffset: null, newExpOffset: null };
  }
  const expId = sess.exp_id;
  let events = [];
  let newWorkspaceOffset = null;
  let newExpOffset = null;
  if (expId) {
    const lastId = readOffset(runDir, sessionId, "exp");
    const newEvents = readEventsAfter(expEventsPath(runDir, expId), lastId);
    events = newEvents;
    if (newEvents.length > 0)
      newExpOffset = newEvents[newEvents.length - 1].id;
  } else {
    const lastId = readOffset(runDir, sessionId, "workspace");
    const newEvents = readEventsAfter(workspaceEventsPath(runDir), lastId);
    events = newEvents;
    if (newEvents.length > 0)
      newWorkspaceOffset = newEvents[newEvents.length - 1].id;
  }
  const text = events.length > 0 ? formatDirectiveText(events) : null;
  if (newWorkspaceOffset || newExpOffset) {
    writeOffset(runDir, sessionId, {
      workspaceId: newWorkspaceOffset,
      expId: newExpOffset
    });
  }
  unlinkIfExists(markerFile(runDir, sessionId));
  return { text, newWorkspaceOffset, newExpOffset };
}

// factory.ts
import * as crypto from "crypto";
function makeRegister(host) {
  function deriveSessionId() {
    const hash = crypto.createHash("sha256").update(process.cwd()).digest("hex").slice(0, 12);
    return `${host}-${hash}`;
  }
  return function register(api) {
    const drainedTexts = [];
    const ensureRegistered = () => {
      const runDir = findEvoRunDir();
      if (!runDir)
        return null;
      const sid = deriveSessionId();
      if (!isRegistered(runDir, sid)) {
        registerSession(runDir, sid, host);
      }
      return { sid, runDir };
    };
    const appendToPayload = (event, text) => {
      if (Array.isArray(event.payload?.input)) {
        event.payload.input.push({
          role: "user",
          content: [{ type: "input_text", text }]
        });
      } else if (Array.isArray(event.payload?.messages)) {
        event.payload.messages.push({
          role: "user",
          content: [{ type: "text", text }]
        });
      }
    };
    api.on("session_start", () => {
      ensureRegistered();
    });
    const scanForEvoCommands = (payload) => {
      try {
        const items = Array.isArray(payload?.input) ? payload.input : [];
        for (const it of items) {
          const args = it?.arguments;
          if (typeof args === "string" && isEvoCommand(args))
            return true;
          if (typeof args === "object" && args) {
            const cmd = args.command ?? args.cmd ?? args.shell;
            if (typeof cmd === "string" && isEvoCommand(cmd))
              return true;
          }
        }
        const msgs = Array.isArray(payload?.messages) ? payload.messages : [];
        for (const m of msgs) {
          const content = Array.isArray(m?.content) ? m.content : [];
          for (const c of content) {
            if (c?.type === "tool_use") {
              const cmd = c?.input?.command ?? c?.input?.cmd;
              if (typeof cmd === "string" && isEvoCommand(cmd))
                return true;
            }
          }
        }
      } catch {}
      return false;
    };
    api.on("before_provider_request", (event, _ctx) => {
      const ctx = ensureRegistered();
      if (!ctx)
        return;
      if (scanForEvoCommands(event.payload)) {
        if (markEngaged(ctx.runDir, ctx.sid)) {
          initOffsetToLatest(ctx.runDir, ctx.sid);
        }
      }
      const result = drainSession(ctx.runDir, ctx.sid);
      if (result.text)
        drainedTexts.push(result.text);
      if (drainedTexts.length === 0)
        return;
      const combined = drainedTexts.join(`
`);
      appendToPayload(event, combined);
      return event.payload;
    });
  };
}

// pi-entry.ts
var pi_entry_default = makeRegister("pi");
export {
  pi_entry_default as default
};
