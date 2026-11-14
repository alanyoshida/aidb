# Design

## Context

`add-kubernetes-driver`'s design (D3) already found that a PVC from `local-path-provisioner` has
no filesystem path the portal can reach directly — unlike the Docker driver's bind mount. For
**config** files that decision routed delivery through a ConfigMap instead. For the **workspace**
(large, read-write, must persist across Pod recreation) a ConfigMap doesn't fit, and D3 explicitly
left workspace write-access unresolved beyond "PVC is still the right choice for the workspace" —
it never specified how the portal itself gets bytes into that PVC.

`checkpoints.py` later filled part of that gap for git operations only: `_git()`
(`portal/appaiforge/checkpoints.py:32`) dispatches on `get_settings().provisioning_driver`, and
under Kubernetes runs `git` inside the agent's container via the Kubernetes exec API
(`_git_via_exec()`, same file, line 42). `guidelines.materialize()` and
`provisioning.delete_system()` were written against the Docker-only assumption and never got the
same treatment — see `proposal.md` for how that breaks guideline delivery and leaks PVCs today.

## Goals / Non-Goals

**Goals:**
- Give `materialize()` a way to write AGENTS.md and the template files into the real workspace
  under the Kubernetes driver.
- Give `delete_system()` a way to delete the real workspace PVC under the Kubernetes driver on
  definitive (admin-only) deletion.
- Handle the startup-ordering hazard: `materialize()` runs at the start of `AgentQueue._execute`,
  before anything confirms the agent's Pod is up.
- Zero behavior change under the Docker driver.

**Non-Goals:**
- A general-purpose "driver-agnostic workspace filesystem" abstraction (e.g. adding
  `write_workspace_file`/`delete_workspace` to the `ProvisioningDriver` Protocol). See Decision 1.
- Changing how config files are delivered (ConfigMap, settled by D3) — out of scope.
- Changing what `archive_system()` / `driver.remove()` do to the workspace — they must keep
  preserving it, unchanged.

## Decisions

### Decision 1 — Dispatch on `provisioning_driver` at the call site, matching `checkpoints._git()`, instead of extending the `ProvisioningDriver` Protocol
`_git()` already solved this exact "local path vs. exec" problem with a plain `if
get_settings().provisioning_driver == "kubernetes"` branch, not a Protocol method. Mirroring that
keeps `materialize()`/`delete_system()` consistent with the one place in the codebase that already
does this correctly, and keeps this fix small. Alternative considered: add
`write_workspace_file()`/`delete_workspace()` to `ProvisioningDriver` (`drivers/base.py`), which
would be more consistent with how `ensure_ready`/`remove`/`is_healthy` are already modeled as
driver methods — rejected for this change because it's a larger refactor (touches the Protocol,
both driver implementations, and every test double) for a bug fix whose only established precedent
in this codebase uses the simpler dispatch. Worth revisiting if a third driver-specific workspace
operation shows up.

### Decision 2 — Write via `tar` over exec stdin, not one `cat >` exec per file
`materialize()` writes two things: `AGENTS.md` and N template files under `portal_templates/`. A
Kubernetes exec command with `stdin=True` can pipe into `tar -xf - -C /workspace` — the same
technique `kubectl cp` itself uses — letting a single exec call create the `portal_templates/`
subdirectory and every file inside it in one shot, instead of N+1 separate `connect_get_namespaced_pod_exec`
round trips (one `mkdir -p`, then one `cat > file` per file). Build the tar in memory from the same
bytes `materialize()` already has (from `current_content()` and `TEMPLATES_PACKAGE_DIR`) — no
on-disk temp file needed.

### Decision 3 — Wait for the agent container to be started, not for `is_healthy()`
`KubernetesProvisioningDriver.is_healthy()` (kubernetes_driver.py:275) requires the `agent`
container's *readiness probe* to pass — a stronger and slower condition than "the container
process exists and a shell can be exec'd into it," and one that could itself depend on
AGENTS.md already being in place, risking a deadlock. Instead, poll `read_namespaced_pod` for the
`agent` entry in `pod.status.container_statuses` to have `started: true` (or `phase == "Running"`
if `container_statuses` isn't populated yet), with a bounded timeout and backoff. On timeout,
raise rather than silently skip, and let `AgentQueue._execute`'s existing
`except OSError: log.warning(...)` guard around `materialize()` (agent_queue.py:~265) keep
degrading the same way it does today for a local write failure — broadening that except clause (or
raising an `OSError` subclass from the new code path) so the run still proceeds without guidelines
instead of crashing, exactly like a Docker-side write failure does today.

### Decision 4 — Delete the PVC from `delete_system()`, keyed off the existing `_workspace_pvc_name()`, only on this path
`delete_namespaced_persistent_volume_claim(name, namespace)` under the same `if driver ==
"kubernetes"` branch as Decision 1, ignoring a 404 (idempotent, matching the existing
delete-then-create pattern already used for Traefik CRDs in the same file). This only runs from
`delete_system()`. `stop_and_remove()` → `driver.remove()` is untouched, so archive and
reprovision keep the PVC exactly as `_ensure_workspace_pvc()`'s own docstring intends.

## Risks / Trade-offs

- **[Risk] Polling for container readiness adds latency to the first run of every Kubernetes
  system** → Mitigation: bound the poll with a short timeout matched to typical Pod startup in
  this cluster (verify empirically during implementation); this only affects the Kubernetes driver,
  and only the first `materialize()` call after a Pod (re)creation.
- **[Risk] Exec-based tar write can partially succeed (e.g. network drop mid-stream), leaving a
  half-written `portal_templates/`** → Mitigation: write to a temp path inside the container and
  rename into place with a second, trivial exec call (`mv`), matching the atomicity the Docker path
  already gets for free from `shutil.copyfile`+`os.makedirs` being local and fast; acceptable
  because a retried `materialize()` on the next run overwrites deterministically either way (same
  byte-for-byte guarantee the existing test `test_templates_materializados_iguais_ao_original`
  already checks).
- **[Risk] PVC deletion is irreversible and admin-triggered** → Already true today for the Docker
  path's `shutil.rmtree`; no new exposure, just making Kubernetes match it instead of silently no-op'ing.

## Migration Plan

- No migration of existing systems: this only changes behavior under the Kubernetes driver, which
  has no systems running against it outside `deploy-portal-in-cluster`'s own validation yet.
- Rollout: land behind the existing driver selection (nothing new to flag) — Docker-driver systems
  see zero behavior change; Kubernetes-driver systems start getting real guideline delivery and
  real PVC cleanup as soon as this ships.
- Rollback: reverting this change returns `materialize()`/`delete_system()` to today's silent-gap
  behavior under Kubernetes; no data migration needed either way since the local directories they
  used to touch were always inert under that driver.

## Open Questions

- Exact poll timeout/backoff for container readiness (Decision 3) — tune during implementation
  against real Pod startup times; doesn't change the approach or the spec.
