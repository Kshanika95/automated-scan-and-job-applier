"""Thin wrapper around headless Claude Code (`claude -p`) that returns schema-validated JSON.

Uses the person's own Claude subscription through the Claude Code CLI: no tools, no MCP servers,
a fixed system prompt (cached between calls), and a JSON Schema so the reply is validated.
"""
import json, os, subprocess, time
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))  # python3 -I ignores the script folder
import core

LOG = core.LOGS / "llm.log"


class LLMError(RuntimeError):
    """Claude could not answer (usage limit, timeout, invalid output). The worker pauses on this."""


def _env():
    e = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_CODE_") and k != "CLAUDECODE"}
    e["PATH"] = os.pathsep.join([os.path.dirname(core.claude()), os.path.dirname(core.node()), e.get("PATH", "/usr/bin:/bin")])
    return e


def ask_json(system, prompt, schema, model=None, timeout=420, tries=2):
    model = model or core.CONFIG.get("llm_model", "sonnet")
    cmd = [core.claude(), "-p", "--model", model, "--tools", "", "--strict-mcp-config",
           "--system-prompt", system, "--output-format", "json", "--no-session-persistence",
           "--json-schema", json.dumps(schema)]
    last = ""
    for _ in range(tries):
        t0 = time.time()
        try:
            r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout,
                               env=_env(), cwd=str(core.STATE))
        except subprocess.TimeoutExpired:
            last = f"timeout after {timeout}s"
            continue
        try:
            d = json.loads(r.stdout)
        except Exception:
            last = (r.stdout or r.stderr or "")[-600:]
            if "limit" in last.lower():
                break
            continue
        with LOG.open("a") as f:
            f.write(json.dumps({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "model": model, "secs": round(time.time() - t0),
                                "cost_estimate_usd": d.get("total_cost_usd"), "err": d.get("is_error")}) + "\n")
        if d.get("is_error") or d.get("structured_output") is None:
            last = str(d.get("result") or d.get("subtype"))[:600]
            if "limit" in last.lower():
                break
            continue
        return d["structured_output"]
    raise LLMError(last or "no output")
