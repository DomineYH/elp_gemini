#!/usr/bin/env python3
"""Resolve the effective harness/model/effort for delegated roles (MODEL-1).

Usage:
  python3 .routing/resolve_models.py                      # all roles
  python3 .routing/resolve_models.py --role implementer   # one role
  python3 .routing/resolve_models.py --overrides req.json # apply request.prompt_overrides from a file
  python3 .routing/resolve_models.py --profile high_assurance
  python3 .routing/resolve_models.py --json               # machine-readable output

Precedence per field, independently (harness, model, effort):
  1. request.prompt_overrides.roles.<role>.<field>
  2. request.prompt_overrides.default.<field>
  3. models.profiles[active_profile].roles.<role>.<field>
  4. models.roles.<role>.<field>
  5. models.default.<field>
  6. request.runtime_defaults.<field>
A value is "missing" when the key is absent, null, empty or whitespace (MODEL-1).
The host session is never resolved (MODEL-4). The policy file does not carry settings (MODEL-5).
"""
import argparse
import json
import sys
from pathlib import Path

FIELDS = ("harness", "model", "effort")
RETIRED = {"coordinator", "final-verifier", "final_verifier", "host"}


def missing(v):
    return v is None or (isinstance(v, str) and v.strip() == "")


def resolve_role(role, models, overrides, runtime_defaults, profile):
    prof_roles = models.get("profiles", {}).get(profile, {}).get("roles", {})
    layers = [
        (f"prompt_overrides.roles.{role}", overrides.get("roles", {}).get(role, {})),
        ("prompt_overrides.default", overrides.get("default", {})),
        (f"models.profiles.{profile}.roles.{role}", prof_roles.get(role, {})),
        (f"models.roles.{role}", models.get("roles", {}).get(role, {})),
        ("models.default", models.get("default", {})),
        ("request.runtime_defaults", runtime_defaults),
    ]
    out = {}
    for f in FIELDS:
        out[f] = {"value": None, "source": None}
        for name, layer in layers:
            v = (layer or {}).get(f)
            if not missing(v):
                out[f] = {"value": v, "source": name}
                break
    return out


def preflight(role, resolved, models):
    """Static adapter check (MODEL-3). Returns list of problems."""
    problems = []
    h, e = resolved["harness"]["value"], resolved["effort"]["value"]
    if h and h in models.get("adapters", {}):
        efforts = models["adapters"][h].get("efforts", [])
        if e and e not in efforts:
            problems.append(f"effort '{e}' not in adapters.{h}.efforts {efforts} -> BLOCKED for {role} (MODEL-3)")
        allowed_models = models["adapters"][h].get("models")
        m = resolved["model"]["value"]
        if allowed_models and m and m not in allowed_models:
            problems.append(f"model '{m}' not in adapters.{h}.models -> BLOCKED for {role} (MODEL-3)")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--routing-dir", default=None, help="directory holding models.json (default: this script's directory)")
    ap.add_argument("--role", help="resolve one role only")
    ap.add_argument("--overrides", help="JSON file containing a request or a prompt_overrides object")
    ap.add_argument("--profile", help="override models.active_profile for this resolution")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    rdir = Path(a.routing_dir) if a.routing_dir else Path(__file__).resolve().parent
    models = json.loads((rdir / "models.json").read_text(encoding="utf-8"))
    policy_path = rdir / "jev_task_routing.json"
    policy_roles = list(json.loads(policy_path.read_text(encoding="utf-8")).get("roles", {})) if policy_path.exists() else list(models["roles"])

    overrides, runtime_defaults = {}, {}
    if a.overrides:
        req = json.loads(Path(a.overrides).read_text(encoding="utf-8"))
        overrides = req.get("prompt_overrides", req) or {}
        runtime_defaults = req.get("runtime_defaults", {}) or {}
        bad = (set(overrides.get("roles", {})) & RETIRED) | (set(overrides.get("roles", {})) - set(policy_roles))
        if bad:
            print(f"ERROR: prompt_overrides name unregistered or retired role IDs {sorted(bad)} (MODEL-2/MODEL-4)", file=sys.stderr)
            return 2

    profile = a.profile or models.get("active_profile", "standard")
    if profile not in models.get("profiles", {}):
        print(f"ERROR: profile '{profile}' not defined in models.json", file=sys.stderr)
        return 2

    roles = [a.role] if a.role else policy_roles
    if a.role and a.role not in policy_roles:
        print(f"ERROR: unknown role '{a.role}'; registered: {policy_roles}", file=sys.stderr)
        return 2

    result, blocked = {}, 0
    for r in roles:
        res = resolve_role(r, models, overrides, runtime_defaults, profile)
        probs = preflight(r, res, models)
        unresolved = [f for f in FIELDS if res[f]["value"] is None]
        result[r] = {"resolved": res, "problems": probs, "unresolved_fields": unresolved}
        blocked += bool(probs)

    if a.json:
        print(json.dumps({"profile": profile, "roles": result}, indent=2))
    else:
        print(f"profile: {profile}")
        for r, info in result.items():
            res = info["resolved"]
            print(f"\n{r}")
            for f in FIELDS:
                v, src = res[f]["value"], res[f]["source"]
                print(f"  {f:8} = {v!s:20} <- {src or '(unset: omit argument, use verified launch default)'}")
            for p in info["problems"]:
                print(f"  !! {p}")
        print(f"\n{len(result)} role(s), {blocked} BLOCKED by static preflight")
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
