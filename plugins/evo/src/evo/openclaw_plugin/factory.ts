// Shared register-factory for hosts that use pi's ExtensionAPI shape
// (openclaw, pi). Each host's entry file calls makeRegister(host) to bind
// its own host string into the session record. Two reasons this matters:
//
//   1. The host string drives observability — `evo direct` enumeration,
//      dashboard listing, and `inject/sessions/<sid>.json` all reflect
//      what's recorded here. Tagging pi sessions as "openclaw" (the
//      pre-0.4.4 bug) made pi traffic invisible to per-host metrics.
//   2. Session ids are prefixed `<host>-<cwd_hash>`, so running pi and
//      openclaw concurrently against the same workspace produces two
//      distinct session records instead of colliding on one.

import {
  drainSession,
  findEvoRunDir,
  initOffsetToLatest,
  isEvoCommand,
  isRegistered,
  markEngaged,
  registerSession,
} from "../opencode_plugin/drain.js"
import * as crypto from "crypto"

interface PiExtensionAPI {
  on(event: string, handler: (event: any, ctx: any) => any): void
}

export function makeRegister(host: string): (api: PiExtensionAPI) => void {
  function deriveSessionId(): string {
    const hash = crypto.createHash("sha256").update(process.cwd()).digest("hex").slice(0, 12)
    return `${host}-${hash}`
  }

  return function register(api: PiExtensionAPI): void {
    // In-memory cache of directive text already drained from disk. We keep
    // appending these to every outbound LLM payload so that subagents
    // (which share sid via cwd hash) also see the directive on their own
    // first call.
    const drainedTexts: string[] = []

    const ensureRegistered = (): { sid: string; runDir: string } | null => {
      const runDir = findEvoRunDir()
      if (!runDir) return null
      const sid = deriveSessionId()
      if (!isRegistered(runDir, sid)) {
        registerSession(runDir, sid, host)
      }
      return { sid, runDir }
    }

    const appendToPayload = (event: any, text: string): void => {
      if (Array.isArray(event.payload?.input)) {
        event.payload.input.push({
          role: "user",
          content: [{ type: "input_text", text }],
        })
      } else if (Array.isArray(event.payload?.messages)) {
        event.payload.messages.push({
          role: "user",
          content: [{ type: "text", text }],
        })
      }
    }

    api.on("session_start", () => {
      ensureRegistered()
    })

    // Best-effort engagement detection: scan the outbound LLM payload's
    // recent messages for tool calls that ran `evo …`. Both OpenAI
    // (payload.input items with type:"function_call") and Anthropic
    // (payload.messages tool_use blocks) expose recent tool calls in
    // their payloads. We sniff the command string and flip engagement
    // if we see an evo invocation. Heuristic — agents could wrap the
    // call in a script — but matches the common case of `bash -c "evo …"`
    // or direct tool calls.
    const scanForEvoCommands = (payload: any): boolean => {
      try {
        // OpenAI Responses-style: payload.input entries with arguments
        const items = Array.isArray(payload?.input) ? payload.input : []
        for (const it of items) {
          const args = it?.arguments
          if (typeof args === "string" && isEvoCommand(args)) return true
          if (typeof args === "object" && args) {
            const cmd = args.command ?? args.cmd ?? args.shell
            if (typeof cmd === "string" && isEvoCommand(cmd)) return true
          }
        }
        // Anthropic Messages-style: payload.messages with tool_use blocks
        const msgs = Array.isArray(payload?.messages) ? payload.messages : []
        for (const m of msgs) {
          const content = Array.isArray(m?.content) ? m.content : []
          for (const c of content) {
            if (c?.type === "tool_use") {
              const cmd = c?.input?.command ?? c?.input?.cmd
              if (typeof cmd === "string" && isEvoCommand(cmd)) return true
            }
          }
        }
      } catch {
        // Defensive: never break the LLM call on a scan error
      }
      return false
    }

    api.on("before_provider_request", (event: any, _ctx: any) => {
      const ctx = ensureRegistered()
      if (!ctx) return

      // Engagement detection — flip the flag if the outbound payload
      // shows the agent has been running `evo` commands.
      if (scanForEvoCommands(event.payload)) {
        if (markEngaged(ctx.runDir, ctx.sid)) {
          initOffsetToLatest(ctx.runDir, ctx.sid)
        }
      }

      // Drain any new on-disk events (advances offset → consumed_by++).
      const result = drainSession(ctx.runDir, ctx.sid)
      if (result.text) drainedTexts.push(result.text)

      // Replay every previously drained directive on every call so
      // subagents that share sid also receive the content directly.
      if (drainedTexts.length === 0) return
      const combined = drainedTexts.join("\n")
      appendToPayload(event, combined)
      return event.payload
    })
  }
}
