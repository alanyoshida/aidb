# Proposal

## Why

Under the Kubernetes provisioning driver (`container-driver-kubernetes`), the portal process has
no local or mounted path to a system's workspace — it is a PVC mounted only inside the agent's
Pod, unlike the Docker driver's host bind mount. `guidelines.materialize()` and
`provisioning.delete_system()` were never updated for this: both still assume
`get_settings().workspaces_dir` is a path the portal can read and write directly, with no check of
the active driver.

The result, found while implementing `deploy-portal-in-cluster`: under the Kubernetes driver,
`materialize()` silently writes AGENTS.md and the canonical templates into a local directory
nobody — not the agent, not the system — ever sees, so every run executes against stale or
missing guidelines with no error raised. And `delete_system()`'s `shutil.rmtree` only removes that
same useless local directory on admin-triggered definitive deletion, so the system's real
workspace PVC is never deleted and is orphaned in the cluster.

`checkpoints.py` already solved the identical problem for git operations: `_git()` dispatches on
`get_settings().provisioning_driver` and runs git inside the agent's container via the Kubernetes
exec API (`_git_via_exec()`) when the driver is Kubernetes. `materialize()` and `delete_system()`
need the same treatment.

## What Changes

- `guidelines.materialize()` writes AGENTS.md and the template files into the system's real
  workspace under the Kubernetes driver by executing the write inside the agent's container (via
  the Kubernetes exec API), instead of writing to the portal's own local filesystem. Behavior under
  the Docker driver is unchanged.
- `materialize()` handles the case where the agent's Pod/container is not yet ready when it runs
  (it currently runs at the very start of `AgentQueue._execute`, before the harness confirms
  readiness) — by waiting for readiness or by being resequenced relative to session/pod startup —
  instead of failing the exec silently or crashing the run.
- `provisioning.delete_system()` deletes the system's real persistent workspace storage (the
  workspace PVC) via the Kubernetes API under the Kubernetes driver, in addition to (or instead of)
  the local `shutil.rmtree`, so a definitive deletion does not orphan cluster storage. Behavior
  under the Docker driver is unchanged.
- The non-definitive paths (`archive_system`, `stop_and_remove`/`driver.remove()`) are **not**
  changed — they intentionally keep the workspace PVC so an archived or reprovisioned system does
  not lose its workspace.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `container-driver-kubernetes`: adds the requirement that the Kubernetes driver give the portal a
  way to write files into a system's workspace and to permanently delete that workspace's storage,
  given that the portal has no local or mounted path to the PVC. Without this, the existing
  "Armazenamento persistente de workspace e config" and "Paridade observável entre drivers de
  provisionamento" requirements cannot actually be satisfied end-to-end for guideline delivery and
  definitive deletion.

## Impact

- **Código**: `portal/appaiforge/guidelines.py` (`materialize`), `portal/appaiforge/provisioning.py`
  (`delete_system`), `portal/appaiforge/drivers/kubernetes_driver.py` (new exec-write helper for the
  workspace, PVC deletion using the existing `_workspace_pvc_name()`), possibly
  `portal/appaiforge/checkpoints.py` if the exec-write helper is factored out for reuse by
  `_git_via_exec`.
- **Testes**: `portal/tests/unit/test_agent_pipeline.py` (materialize coverage),
  `portal/tests/integration/test_kubernetes_driver.py`, `portal/tests/integration/test_provisioning.py`
  (`test_exclusao_remove_container_e_workspace`), `portal/tests/integration/test_driver_parity.py`.
- **Sem mudança**: comportamento sob o driver Docker; `archive_system`/`driver.remove()` (mantêm a
  PVC do workspace de propósito).
