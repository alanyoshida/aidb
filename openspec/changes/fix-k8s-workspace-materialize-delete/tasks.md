# Tasks

## 1. Exec-based workspace write for the Kubernetes driver

- [x] 1.1 Add a workspace-write helper to `kubernetes_driver.py` (e.g.
  `write_workspace_files(system, files: dict[str, bytes])`) that execs `tar -xf - -C /workspace`
  into the `agent` container with the file contents streamed over stdin, mirroring
  `_git_via_exec`'s use of `connect_get_namespaced_pod_exec`. Verify with an integration test
  (kind cluster) that reads the files back inside the Pod via a follow-up `cat` exec.
- [x] 1.2 Add a bounded poll (timeout + backoff) for the `agent` container being started
  (`pod.status.container_statuses` entry for `agent` with `started: true`, falling back to
  `phase == "Running"`), raised as an `OSError` subclass on timeout rather than hanging. Verify
  with a test that points at a Pod stuck in `Pending`/`ContainerCreating` and asserts it raises
  after the timeout instead of blocking indefinitely.
- [x] 1.3 In `guidelines.materialize()`, dispatch on `get_settings().provisioning_driver`: call the
  new write-helper (after the readiness poll from 1.2) under `"kubernetes"`, keep the existing
  local `os.makedirs`/`open`/`shutil.copyfile` path unchanged under `"docker"`. Verify
  `test_guidelines_atualizacao_propaga_para_workspace` and
  `test_templates_materializados_iguais_ao_original` (`portal/tests/unit/test_agent_pipeline.py`)
  still pass unmodified, and add a Kubernetes-driver counterpart to
  `portal/tests/integration/test_kubernetes_driver.py` asserting AGENTS.md and every
  `TEMPLATE_FILES` entry land byte-for-byte inside the Pod's `/workspace` after `materialize()`.
- [x] 1.4 Align `AgentQueue._execute`'s `except OSError: log.warning(...)` guard around
  `materialize()` (`portal/appaiforge/agent_queue.py`) so a Kubernetes-side write/readiness
  failure degrades the run the same way a Docker-side write failure does today (warn, continue
  without guidelines) instead of propagating. Verify with a unit test that forces the Kubernetes
  write path to raise and asserts the run still starts.

## 2. PVC deletion on definitive system deletion

- [x] 2.1 Add a PVC-deletion helper to `kubernetes_driver.py` using
  `delete_namespaced_persistent_volume_claim` and the existing `_workspace_pvc_name()`, treating a
  404 as success (idempotent, matching the delete-then-create 404 handling already used for the
  Traefik CRD objects in the same file). Verify with a unit test asserting a second call after
  deletion does not raise.
- [x] 2.2 In `provisioning.delete_system()`, dispatch on `get_settings().provisioning_driver`: call
  the new PVC-deletion helper under `"kubernetes"` in addition to the existing
  `shutil.rmtree(workspace, ignore_errors=True)`; leave the `"docker"` path unchanged. Verify
  `test_exclusao_remove_container_e_workspace`
  (`portal/tests/integration/test_provisioning.py`, Docker-only) is unaffected, and add a
  Kubernetes integration test to `test_kubernetes_driver.py` asserting the workspace PVC no
  longer exists (`read_namespaced_persistent_volume_claim` raises 404) after `delete_system()`.
- [x] 2.3 Add a regression test next to
  `test_workspace_sobrevive_a_recriacao_do_pod` in `test_kubernetes_driver.py` asserting that
  `archive_system()` (→ `stop_and_remove()` → `driver.remove()`) leaves the workspace PVC in
  place — guarding the scope boundary from `design.md` Decision 4 (only `delete_system()` deletes
  the PVC).

## 3. Driver-parity verification

- [x] 3.1 Extend `portal/tests/integration/test_driver_parity.py` (alongside
  `test_paridade_provisionar_publicar_e_reconciliar`) with a case that materializes guidelines and
  then definitively deletes a system under both drivers, asserting the same externally observable
  outcome (guidelines reach the real workspace; the workspace is gone after deletion) for each.
  Verify the new case fails against the pre-fix code path and passes after tasks 1-2 are done.

## 4. Documentation

- [x] 4.1 Update the `kubernetes_driver.py` module docstring — which already records the "PVC not
  reachable by the portal" finding without a resolution — and `checkpoints.py`'s `workspace_dir()`
  docstring, to point at the new exec-write/PVC-delete mechanism so this gap isn't rediscovered.
  Verify by re-reading both docstrings against the shipped code.
