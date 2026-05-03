# Execution Rules

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

# Gstack + OMC Integrated Workflow (CLAUDE.md-only)

## gstack
Use /browse from gstack for all web browsing. Never use mcp__claude-in-chrome__* tools.
Available skills: /office-hours, /plan-ceo-review, /plan-eng-review, /plan-design-review,
/plan-devex-review, /autoplan, /design-consultation, /design-shotgun, /design-html,
/review, /design-review, /devex-review, /investigate, /qa, /qa-only, /ship,
/land-and-deploy, /canary, /benchmark, /browse, /open-gstack-browser,
/setup-browser-cookies, /setup-deploy, /retro, /document-release, /codex, /cso,
/careful, /freeze, /guard, /unfreeze, /gstack-upgrade, /learn.

## Skill routing
When the user's request matches an available gstack skill, ALWAYS invoke it using the Skill tool
as your FIRST action. Do NOT answer directly, do NOT use other tools first.
The skill has specialized workflows that produce better results than ad-hoc answers.

---

## CLAUDE.md-only Integration Principle

This repository connects gstack and OMC **through this single CLAUDE.md only**.
By default, do not create `.omc/skills/`, `.omc/specs/`, `docs/designs/`,
wrapper scripts, or any repo-local handoff files.

gstack artifacts are read directly from `$HOME/.gstack/projects/...`,
and this CLAUDE.md governs role separation and handoff rules.

---

## Role Separation

### What gstack owns
- Problem definition, scope adjustment, plan approval
- Design review, DX review, architecture review
- Code review, QA, release, deployment, post-deploy monitoring
- Browser-based verification and screenshot collection

### What OMC owns
- Implementation execution based on approved gstack plans
- Fix execution based on `/investigate` results
- Implementation finalization requiring iterative verify/fix cycles
- Parallel task decomposition and execution acceleration

### Single source of truth
- When an approved gstack plan document exists, **that document is the sole authority**.
- OMC must not recreate a separate product planning framework; it implements the approved plan.
- OMC's `deep-interview`, `plan`, `ralplan` are not used as the default planning system.
  They are only used when the user **explicitly requests OMC-native planning**.
- Default planning authority belongs to gstack.

### OMC mode defaults
- Default multi-agent execution: `/team`
- Small-scope, well-constrained implementation: `autopilot`
- Bugs/fixes that must be resolved to completion: `ralph`
- Large-scale parallel cleanup/refactoring: `ulw`
- `swarm` is a compatibility alias that routes to Team since v4.1.7+. Use `/team` in new prompts.
- `ultrapilot` is likewise a compatibility path. Use `/team` in new prompts.

---

## Prefix-aware gstack usage rules

If any gstack skill's preamble output shows `SKILL_PREFIX: true`,
use `/gstack-*` names for skill recommendations and invocations
(e.g., `/gstack-qa` instead of `/qa`, `/gstack-ship` instead of `/ship`).

Disk paths remain unchanged. When reading skill files, always resolve from
`$HOME/.claude/skills/gstack/[skill-name]/SKILL.md`.

---

## Pre-implementation requirement: Resolve gstack plan documents and test plans

Before starting any implementation, fix, refactor, or `/review` follow-up with OMC,
you must locate and validate the current branch's gstack plan document and test plan.

```bash
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
REPO_NAME=$(basename "$REPO_ROOT")
SLUG=$($HOME/.claude/skills/gstack/browse/bin/remote-slug 2>/dev/null || basename "$REPO_ROOT")
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null | tr '/' '-' || echo 'no-branch')

# Locate design document
DESIGN=$(ls -t "$HOME/.gstack/projects/$SLUG"/*-"$BRANCH"-design-*.md 2>/dev/null | head -1)
[ -z "$DESIGN" ] && DESIGN=$(ls -t "$HOME/.gstack/projects/$SLUG"/*-design-*.md 2>/dev/null | head -1)

if [ -n "$DESIGN" ]; then
  echo "DESIGN=$DESIGN"
  DESIGN_BRANCH=$(grep -m1 '^Branch:' "$DESIGN" | sed 's/^Branch:[[:space:]]*//')
  DESIGN_REPO=$(grep -m1 '^Repo:' "$DESIGN" | sed 's/^Repo:[[:space:]]*//')
  [ -n "$DESIGN_BRANCH" ] && echo "DESIGN_BRANCH=$DESIGN_BRANCH"
  [ -n "$DESIGN_REPO" ] && echo "DESIGN_REPO=$DESIGN_REPO"
fi

# Locate test plan (/autoplan artifact)
TEST_PLAN=$(ls -t "$HOME/.gstack/projects/$SLUG"/*-"$BRANCH"-test-plan-*.md 2>/dev/null | head -1)
[ -z "$TEST_PLAN" ] && TEST_PLAN=$(ls -t "$HOME/.gstack/projects/$SLUG"/*-test-plan-*.md 2>/dev/null | head -1)
[ -n "$TEST_PLAN" ] && echo "TEST_PLAN=$TEST_PLAN"
```

### Validation rules
- Always look for a **current-branch document** first; fall back to the latest document under the same slug only if none is found.
- If the `Branch:` header exists and differs from the current branch, do not use that document as the implementation basis.
- If the `Repo:` header exists and differs from the current repo/slug, do not use that document as the implementation basis.
- If a valid document is found, read it in full. Use these sections as the primary execution reference:
  - `Recommended Approach` = implementation contract
  - `Success Criteria` = completion acceptance gate
- If a test plan exists, read it alongside the design document and use it as the basis for writing/updating tests.
- If no valid document is found and the task is not Small, do not proceed with implementation — enter the gstack planning phase first.

---

## Gstack artifact path summary

| Skill | Artifact path | Filename pattern |
|-------|--------------|-----------------|
| /office-hours | ~/.gstack/projects/$SLUG/ | {user}-{branch}-design-{datetime}.md |
| /autoplan | ~/.gstack/projects/$SLUG/ | {user}-{branch}-test-plan-{datetime}.md |
| /design-shotgun | ~/.gstack/projects/$SLUG/designs/ | PNG + approved.json |
| /design-consultation | Project root | DESIGN.md |

/plan-ceo-review, /plan-eng-review, and /plan-design-review do not generate files.
They read existing design documents and review them interactively. Changing Status to APPROVED constitutes "finalization."

---

## Design artifact reference for UI work

When implementing or modifying UI, also check the following path:

```bash
$HOME/.gstack/projects/$SLUG/designs/
```

Priority order:
1. `approved.json`
2. Approved PNG mockups
3. Related comparison board context

Rules:
- Raw design artifacts (`approved.json`, mockup PNGs, comparison boards)
  must **always** remain in `$HOME/.gstack/projects/$SLUG/designs/`.
- By default, do not copy these to `docs/designs/` or any other repo-local directory.
- Only copy **text plan documents (.md)** to the repo when the user explicitly requests
  archival. Even then, the canonical source remains `$HOME/.gstack/projects/...`.

---

## OMC execution contract

All OMC prompts should include the following information where available:
- gstack plan document path
- Test plan path (if one exists)
- Current branch name
- Implementation scope summary
- Implementation rules per `Recommended Approach`
- Completion criteria per `Success Criteria`
- Approved design artifact path (if UI work)

### OMC execution rules
- Implement only the approved scope.
- Do not create or redefine product scope.
- Do not change existing architecture unless the plan document says to.
- The following are considered **direct blast radius** and may be addressed alongside the approved change:
  - Broken tests
  - Type errors / import errors / build errors
  - Adjacent module changes required to make the approved change work
- Add or update tests so that each `Success Criteria` item is verifiable.
- If a test plan exists, write tests based on that plan's test matrix.
- Bug fixes follow the order: reproduce → root cause fix → regression test → re-verify.

### Browser/QA/deployment rules
- Web browsing, UI verification, browser screenshots, and staging/prod checks are gstack's responsibility.
- Do not create OMC flows for these tasks.
- For authenticated QA, use `/setup-browser-cookies` first if needed.
- Run `/setup-deploy` before the first deployment automation.

---

## Task sizing and entry point recommendation

When a user request is received, first classify the task into one of these five sizes.

### Classification criteria

**[Large]**
- New product / new subsystem creation
- Open-ended scope or ambiguous requirements
- Multiple axes involved (e.g., frontend + backend + infra)
- UI, DX, and architecture review all needed
- Likely changes to directory structure / data model / deployment flow

**[Medium]**
- Clear feature addition but broad file/module impact
- New API / new page / new workflow added
- New test writing required
- Primarily one axis (UI or DX or architecture)

**[Small]**
- Localized change to 3 or fewer files
- Button / text / style / config / minor branch changes
- Single, clear failure point

**[Bug fix]**
- Error messages, exceptions, broken behavior, reproducible failures
- "Why isn't this working," "error," "bug," "broken" patterns

**[Refactor]**
- Structural improvement with no functional change
- Deduplication, performance cleanup, boundary cleanup, file reorganization

### Recommendation output format

Always recommend in the following format:

```text
Task size: [Large/Medium/Small/Bug fix/Refactor]
Rationale: [1-2 key signals]

Recommended entry point:
[Command or prompt]

Copy-paste:
[Ready-to-use form]

Reason: [1-line explanation]
```

### Default entry points by size

#### [Large]
- If requirements are still vague: `/office-hours` → `/autoplan`
- If requirements are fairly clear but span 2+ axes: `/autoplan`
- Implementation defaults to `/team`.

```text
Recommended entry point: /office-hours → /autoplan → /team

Copy-paste:
/office-hours
→ (after problem definition)
/autoplan
→ (after plan approval)
team 3:executor "Read the latest valid gstack plan document and test-plan for the current branch first. Implement only the Recommended Approach. Use Success Criteria as the acceptance gate. Add/update tests so each criterion is verifiable. For UI work, check $HOME/.gstack/projects/<slug>/designs/approved.json and approved PNGs first."

Reason: Large tasks need CEO/design/DX/engineering axes locked together to minimize rework.
```

#### [Medium]
- UI-focused: `/plan-design-review`
- API/CLI/SDK/docs-focused: `/plan-devex-review`
- Data flow/performance/test/structure-focused: `/plan-eng-review`
- If 2+ axes are mixed: `/autoplan`
- Implementation uses `autopilot` or `/team`.

```text
Recommended entry point: /plan-*-review → implementation

Copy-paste:
/plan-eng-review
→ (or /plan-design-review /plan-devex-review)
→ (after plan approval)
autopilot: Read the latest valid gstack plan document and test-plan for the current branch. Implement only the approved scope. Only change existing architecture if the plan says to. Add/update tests so all Success Criteria are verifiable.

Reason: Medium tasks benefit greatly from locking just the dominant review axis before implementation.
```

#### [Small]
- No planning overhead needed; implement directly.
- If an existing gstack plan document exists, read it first and stay within its scope.

```text
Recommended entry point: Implement directly

Copy-paste:
autopilot: If a gstack plan document exists for the current branch, read it first. Implement only [specific task] with minimal scope. Do not make unnecessary structural changes; only update related tests.

Reason: Small tasks benefit from minimizing execution overhead.
```

#### [Bug fix]
- Entry point must always be `/investigate`.
- Fix execution defaults to `ralph`.

```text
Recommended entry point: /investigate → ralph

Copy-paste:
/investigate
→ (after root cause identified)
ralph: Fix only the root cause based on /investigate results. Minimize the patch. First reproduce the failure, then add a regression test, and finally verify the reproduction is gone.

Reason: Bugs fixed without investigation tend to recur or mask the real cause.
```

#### [Refactor]
- If the structural change is broad, go through `/plan-eng-review` first.
- For localized refactoring, enter directly with `ulw` or `autopilot`.

```text
Recommended entry point: (/plan-eng-review if needed) → ulw

Copy-paste:
ulw: Clean up [refactoring scope] with no functional changes. Preserve public APIs. Only add new dependencies when strictly necessary. Ensure all existing tests continue to pass.

Reason: Refactoring benefits from parallel cleanup efficiency, but architecture boundary changes should be locked first.
```

### User override rule

If the user explicitly specifies `large`, `small`, `bug fix`, `refactor`, etc.,
the user's designation takes precedence over automatic classification.

---

## Next step recommendation after task completion

After each gstack skill or OMC execution completes, recommend 1-3 next steps.
Always include **executable commands or copy-paste prompts**.

### Default mapping

| Just completed | Default next step | Copy-paste |
|---|---|---|
| `/office-hours` | `/autoplan` (default) or manual review chain | `/autoplan` |
| `/plan-ceo-review` | Whichever axis is needed: `/plan-design-review`, `/plan-devex-review`, `/plan-eng-review`, or `/autoplan` | `/autoplan` |
| `/plan-design-review` | `/plan-eng-review` if engineering boundaries remain, otherwise start implementation | `/plan-eng-review` or `autopilot: Implement per the latest approved plan` |
| `/plan-devex-review` | `/plan-eng-review` if engineering boundaries remain, otherwise start implementation | `/plan-eng-review` or `autopilot: Implement per the latest approved plan` |
| `/plan-eng-review` | Start implementation | `team 2:executor "Read the latest approved gstack plan document and test-plan, then implement"` |
| `/autoplan` | Start implementation | `team 3:executor "Read the latest approved gstack plan document and test-plan, then implement"` |
| OMC implementation done | Code review | `/review` |
| `/investigate` | Bug fix execution | `ralph: Fix the root cause based on /investigate results` |
| `/review` passed | `/qa {staging_url}` for web/UI, otherwise `/ship` | `/qa https://...` or `/ship` |
| `/review` issues found | Fix then re-review | `team 2:executor "Read the latest plan and /review findings, fix only confirmed issues"` → `/review` |
| `/qa` passed | `/ship` | `/ship` |
| `/qa` bugs found | Fix then re-QA | `ralph: Fix bugs based on /qa findings and make them re-verifiable` → `/qa {url}` |
| `/ship` | `/setup-deploy` if first deploy automation, otherwise `/land-and-deploy` | `/setup-deploy` or `/land-and-deploy` |
| `/land-and-deploy` | `/canary` for high-risk/user-facing/perf-sensitive changes, otherwise done | `/canary` |
| `/canary` healthy | Done; optionally `/retro` later | `/retro` |
| `/cso` | Fix security issues then re-review | `ralph: Fix security issues based on /cso findings` → `/review` |

### Important correction rules
- `/ship` can automatically invoke `/document-release` after PR creation,
  so **do not separately recommend `/document-release`** as a default next step.
- If deployment configuration does not exist before `/land-and-deploy`, always recommend `/setup-deploy` first.
- `/canary` is not a mandatory next step for every deployment.
  Recommend it primarily when any of the following apply:
  - Auth / payment / onboarding / core funnel changes
  - Performance-sensitive page changes
  - Data migration or high production-impact changes

### Recommendation output format

```text
[Completed task name] complete

Next steps:
A) [Most recommended next step]
   Copy-paste: [command or prompt]

B) [Alternative 1]
   Copy-paste: [command or prompt]

C) [Alternative 2]
   Copy-paste: [command or prompt]
```

### Skip rule
- If the user says `skip`, `next`, or `pass`, do not force the recommendation.
- Skip the recommendation and wait for the user's next direct instruction.

---

## Default implementation prompt templates

### Large / mixed-scope implementation
```text
team 3:executor "Read the latest valid gstack plan document and test-plan for the current branch first. Implement only the Recommended Approach. Use Success Criteria as the acceptance gate. Add/update tests so each criterion is verifiable. For UI work, check approved design artifacts first. Do not expand product scope; only clean up direct blast radius."
```

### Medium / constrained feature implementation
```text
autopilot: Read the latest valid gstack plan document and test-plan for the current branch. Implement only the approved scope. Only change existing architecture if the plan says to. Add/update tests so all Success Criteria are verifiable.
```

### Bug fix implementation
```text
ralph: Read /investigate results and related gstack plan documents. Fix only the root cause. First reproduce the failure, apply a minimal patch, add a regression test, then verify the reproduction is gone.
```

### Refactor implementation
```text
ulw: Read related gstack plan documents if they exist. Clean up [refactoring scope] with no functional changes. Preserve public APIs. Do not create unnecessary abstractions. Ensure all existing tests pass.
```

---

## Final priority rules

When priorities conflict, follow this order:

1. User's explicit instruction
2. gstack skill routing rules
3. Approved gstack plan document
4. This CLAUDE.md's role separation / handoff rules
5. OMC execution optimization

The core principle is simple:
- Thinking and planning are locked by gstack.
- Implementation is executed swiftly by OMC.
- Verification, QA, and deployment are gstack's responsibility again.
