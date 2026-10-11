"""Kubernetes manifests stay local to the namespace."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_MANIFESTS = _ROOT / "deploy" / "k8s"


def test_manifests_have_no_host_access() -> None:
    text = "\n".join(path.read_text(encoding="utf-8") for path in _MANIFESTS.rglob("*.yaml"))
    assert "hostPath" not in text
    assert "docker.sock" not in text
    assert "ClusterRole" not in text
    assert "privileged: true" not in text


def test_api_and_cronjob_are_locked_down() -> None:
    api = (_MANIFESTS / "base" / "api-deployment.yaml").read_text(encoding="utf-8")
    cron = (_MANIFESTS / "base" / "cronjob.yaml").read_text(encoding="utf-8")
    secret = (_MANIFESTS / "base" / "secret.yaml").read_text(encoding="utf-8")
    assert "path: /readyz" in api
    assert "path: /healthz" in api
    assert "runAsNonRoot: true" in api
    assert "readOnlyRootFilesystem: true" in api
    assert "allowPrivilegeEscalation: false" in api
    assert "concurrencyPolicy: Forbid" in cron
    assert "activeDeadlineSeconds:" in cron
    assert "ttlSecondsAfterFinished:" in cron
    assert "restartPolicy: Always" in cron
    assert "emptyDir: {}" in cron
    assert "replace-me" in secret
    assert cron.count("runAsNonRoot: true") >= 4
    base = "\n".join(
        path.read_text(encoding="utf-8") for path in (_MANIFESTS / "base").rglob("*.yaml")
    )
    assert ":latest" not in base
    kustomization = (_MANIFESTS / "base" / "kustomization.yaml").read_text(encoding="utf-8")
    assert 'newTag: "0.0.1"' in kustomization
