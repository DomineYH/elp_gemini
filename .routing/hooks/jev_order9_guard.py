#!/usr/bin/env python3
"""Claude Code PreToolUse hook — ORDER-9 launch-channel guard.

Blocks the host from running a delegated role (planner, implementer, task-verifier,
inspector, researcher, tester, advisor) through Claude Code's own Agent/Task subagent
tool instead of a Herdr pane. Host-side read-only intake via subagents stays allowed.

Registered with matcher "Agent|Task". Reads the hook event JSON on stdin, prints a
permissionDecision JSON on stdout, exits 0. Never raises: on internal error it exits 1
(non-blocking; stderr shown to the user only).

Behaviour is configured by <project>/.routing/hooks.json (created by init_routing.sh):
  mode                   "deny" (default) | "ask" | "log"
  allow_subagent_types   subagent types treated as read-only intake, default ["Explore"]
  unlisted_subagent_type what to do with other types when no role/write signal fires:
                         "ask" (default) | "deny" | "allow"
  log                    relative path of the JSONL audit log, default ".routing/hook_log.jsonl"

The hook is a no-op outside projects that have .routing/jev_task_routing.json installed.
"""
import datetime
import json
import os
import re
import sys
from pathlib import Path

AGENT_TOOLS = {"Agent", "Task"}
ORDER_MARKERS = re.compile(
    r"\b(order_id|role_id|work[ _-]?order|acceptance_criteria|write_scope|read_scope|"
    r"verification_plan_ref|testing_decision_ref|evidence_gap|report_to)\b", re.I)
WRITE_SIGNALS = re.compile(
    r"\b(implement|fix(es|ed|ing)?|refactor|patch|edit|modify|change the code|write (the )?(code|tests?|a test)|"
    r"add (a |the )?(feature|endpoint|migration|test)|commit|apply (the )?(diff|patch)|create (a )?(pr|pull request)|"
    r"run (the )?(tests?|suite|e2e|benchmark)|deploy|merge|구현|수정|리팩터|패치|커밋|테스트 실행|배포|머지)\b", re.I)
ROLE_ACTOR = re.compile(r"\b(you are|act as|as the|role[:=]\s*|당신은|역할[:=]\s*)\s*(the\s+)?(%s)\b", re.I)


def find_project_root(start):
    p = Path(start).resolve()
    for d in [p] + list(p.parents):
        if (d / ".routing" / "jev_task_routing.json").is_file():
            return d
    return None


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def emit(decision, reason):
    out = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision}}
    if reason:
        out["hookSpecificOutput"]["permissionDecisionReason"] = reason
    sys.stdout.write(json.dumps(out))
    sys.stdout.flush()


def log_event(root, cfg, record):
    try:
        path = root / cfg.get("log", ".routing/hook_log.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def main():
    raw = sys.stdin.read()
    try:
        event = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return 0
    tool = event.get("tool_name", "")
    if tool not in AGENT_TOOLS:
        return 0

    root = find_project_root(os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or os.getcwd())
    if root is None:
        return 0  # policy not installed here; stay out of the way

    policy = load_json(root / ".routing" / "jev_task_routing.json", {})
    roles = list(policy.get("roles", {}).keys()) or ["planner", "implementer", "task-verifier", "inspector", "researcher", "tester", "advisor"]
    required = (policy.get("delegation", {}).get("launch_channel", {}) or {}).get("required", "herdr_pane")
    cfg = load_json(root / ".routing" / "hooks.json", {})
    mode = cfg.get("mode", "deny")
    allow_types = set(cfg.get("allow_subagent_types", ["Explore"]))
    unlisted = cfg.get("unlisted_subagent_type", "ask")

    ti = event.get("tool_input", {}) or {}
    subagent_type = str(ti.get("subagent_type", "") or "")
    description = str(ti.get("description", "") or "")
    prompt = str(ti.get("prompt", "") or "")
    text = f"{subagent_type}\n{description}\n{prompt}"

    role_words = re.compile(r"(?<![\w-])(%s)(?![\w-])" % "|".join(re.escape(r) for r in roles), re.I)
    role_in_type = role_words.search(subagent_type) is not None
    role_actor = re.compile(ROLE_ACTOR.pattern % "|".join(re.escape(r) for r in roles), re.I).search(text) is not None
    role_mentions = sorted({m.group(1).lower() for m in role_words.finditer(text)})
    order_marker = ORDER_MARKERS.search(text) is not None
    write_signal = WRITE_SIGNALS.search(text) is not None

    decision, reason, matched = "allow", "", []
    if role_in_type or role_actor or (role_mentions and (order_marker or write_signal)):
        decision = "deny"
        matched = role_mentions or [subagent_type]
        reason = (f"ORDER-9: delegated role work ({', '.join(matched)}) must run in a Herdr pane "
                  f"(launch_channel={required}), not via the {tool} subagent tool. Issue a work order and launch the pane; "
                  f"record pane_id. Subagents are allowed only for the host's own read-only intake.")
    elif order_marker:
        decision = "deny"
        matched = ["work-order fields in prompt"]
        reason = (f"ORDER-9: this {tool} call carries work-order fields, so it is a delegated assignment. "
                  f"Delegated assignments run in Herdr panes (launch_channel={required}), never in a host subagent.")
    elif write_signal:
        decision = "deny"
        matched = ["write/execution intent"]
        reason = (f"ORDER-9 / AUTH-1: a host subagent may not implement, edit, test, commit, deploy or merge — "
                  f"that is implementer/tester work and requires a Herdr pane. Subagents are for read-only intake only.")
    elif subagent_type and subagent_type not in allow_types:
        if unlisted == "deny":
            decision, matched = "deny", [f"unlisted subagent_type {subagent_type}"]
            reason = f"ORDER-9: subagent type '{subagent_type}' is not in hooks.json allow_subagent_types; only read-only intake types are allowed."
        elif unlisted == "ask":
            decision, matched = "ask", [f"unlisted subagent_type {subagent_type}"]
            reason = f"jev ORDER-9 guard: subagent type '{subagent_type}' is not in the read-only allow list. Allow only if this is the host's own read-only intake."

    if mode == "log":
        final = "allow"
    elif mode == "ask" and decision == "deny":
        final = "ask"
    else:
        final = decision

    log_event(root, cfg, {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "session_id": event.get("session_id"), "tool": tool, "subagent_type": subagent_type,
        "description": description[:200], "prompt_head": prompt[:200].replace("\n", " "),
        "matched": matched, "decision": final, "mode": mode,
    })

    if final == "allow":
        return 0  # silent allow
    emit(final, reason)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # never block on our own bug
        sys.stderr.write(f"jev_order9_guard: internal error, not blocking: {e}\n")
        sys.exit(1)
