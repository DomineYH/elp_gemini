#!/usr/bin/env python3
"""Additive migration of a user-edited .routing/models.json to the current models.schema.json.

Usage: python3 migrate_models.py <user_models.json> <shipped_models.json> [--dry-run]

Never changes roles, default, active_profile, profiles or router. Only:
  - adds adapters.<harness>.launch_channels = ["herdr_pane"] where missing (ORDER-9)
  - adds an adapters entry for every harness used by a role (profile or roles) that has none,
    copied from the shipped file when available, otherwise synthesised from the efforts in use
  - adds shipped adapters that the user file lacks entirely
  - updates version / requires_policy_version to the shipped values
Prints one line per change; exit 0 (changed or not), 1 on read error.
"""
import json
import sys
from pathlib import Path


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv
    if len(args) != 2:
        print(__doc__)
        return 1
    user_p, ship_p = Path(args[0]), Path(args[1])
    try:
        user = json.loads(user_p.read_text(encoding="utf-8"))
        ship = json.loads(ship_p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"migrate_models: cannot read inputs: {e}")
        return 1

    changes = []
    adapters = user.setdefault("adapters", {})
    ship_ad = ship.get("adapters", {})

    # harnesses actually used by roles (base roles + every profile)
    used = {}
    for rid, r in (user.get("roles") or {}).items():
        if r.get("harness"):
            used.setdefault(r["harness"], set()).add(r.get("effort"))
    for prof in (user.get("profiles") or {}).values():
        for rid, r in (prof.get("roles") or {}).items():
            if r.get("harness"):
                used.setdefault(r["harness"], set()).add(r.get("effort"))

    for h, efforts in used.items():
        if h not in adapters:
            if h in ship_ad:
                adapters[h] = json.loads(json.dumps(ship_ad[h]))
                extra = sorted(e for e in efforts if e and e not in adapters[h].get("efforts", []))
                if extra:
                    adapters[h]["efforts"] = adapters[h].get("efforts", []) + extra
                    adapters[h]["notes"] = (adapters[h].get("notes", "") + f" | migration added efforts in use {extra}; verify against the installed adapter").strip(" |")
                changes.append(f"added adapters.{h} from shipped defaults" + (f" (+ efforts {extra})" if extra else ""))
            else:
                adapters[h] = {"efforts": sorted(e for e in efforts if e), "launch_channels": ["herdr_pane"],
                               "notes": "auto-added by migrate_models.py from efforts in use; verify against the installed adapter"}
                changes.append(f"added adapters.{h} synthesised from roles in use")

    for h, ad in adapters.items():
        if ad.get("launch_channels") != ["herdr_pane"]:
            ad["launch_channels"] = ["herdr_pane"]
            changes.append(f"set adapters.{h}.launch_channels = ['herdr_pane'] (ORDER-9)")

    for h, ad in ship_ad.items():
        if h not in adapters:
            adapters[h] = json.loads(json.dumps(ad))
            changes.append(f"added adapters.{h} (present in shipped defaults, absent in yours)")

    for k in ("version", "requires_policy_version"):
        if ship.get(k) and user.get(k) != ship.get(k):
            changes.append(f"{k}: {user.get(k)!r} -> {ship[k]!r}")
            user[k] = ship[k]

    if not changes:
        print("    models.json: already current, nothing to migrate")
        return 0
    for c in changes:
        print(f"    models.json migration: {c}")
    if not dry:
        bak = user_p.with_suffix(user_p.suffix + ".pre-migrate.bak")
        bak.write_text(user_p.read_text(encoding="utf-8"), encoding="utf-8")
        user_p.write_text(json.dumps(user, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"    models.json migrated (previous copy: {bak.name}); roles/default/profiles/router untouched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
