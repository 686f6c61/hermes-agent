"""The Linux CUDA engine needs glibc 2.38; below it the host must not try.

Upstream builds the Linux CUDA archives in an `nvidia/cuda:*-devel-ubuntu24.04`
container while the CPU and Vulkan jobs still run on ubuntu-22.04, so at
b11370 the CUDA engine carries GLIBC_2.38 (`libggml-cuda.so` x64,
`libggml-base.so` arm64) and the Vulkan build of the same release carries
GLIBC_2.34. `backend: auto` on Ubuntu 22.04 used to choose CUDA, download it
and die in verify(); these tests pin the gate that answers first.
"""

from __future__ import annotations

import pytest

import pm
from pm import glibc
from pm.package import InstallError, floor_reason


def _below(monkeypatch, version):
    monkeypatch.setattr("pm.package.host_version", lambda: version)


def test_cuda_declares_the_measured_floor_per_linux_target():
    package = pm.get_package("llamacpp-cuda")
    assert package.glibc_floor == {"linux-x64": (2, 38), "linux-arm64": (2, 38)}
    # A floor on a target the package does not publish would never be read.
    assert set(package.glibc_floor) <= set(package.assets)
    assert pm.get_package("llamacpp-vulkan").glibc_floor == {"linux-x64": (2, 34)}


def test_floor_reason_names_the_host_and_the_required_version(monkeypatch):
    _below(monkeypatch, (2, 35))
    reason = floor_reason(pm.get_package("llamacpp-cuda"), "linux-x64", host_target="linux-x64")
    assert reason is not None
    assert "glibc 2.38" in reason
    assert "glibc 2.35" in reason


@pytest.mark.parametrize("host", [(2, 38), (2, 39), (2, 40)])
def test_a_host_at_or_above_the_floor_is_not_gated(monkeypatch, host):
    _below(monkeypatch, host)
    assert floor_reason(pm.get_package("llamacpp-cuda"), "linux-x64", host_target="linux-x64") is None


def test_a_cross_target_stage_is_never_gated(monkeypatch):
    # Staging arm64 from an x64 host is building bytes for someone else.
    _below(monkeypatch, (2, 35))
    assert floor_reason(pm.get_package("llamacpp-cuda"), "linux-arm64", host_target="linux-x64") is None


@pytest.mark.parametrize("libc", ["musl 1.2.4", "", "glibc", "glibc 2"])
def test_a_host_without_a_readable_glibc_keeps_the_gate_open(monkeypatch, libc):
    monkeypatch.setattr(glibc.os, "confstr", lambda name: libc or None)
    monkeypatch.setattr(glibc.platform, "libc_ver", lambda: ("", ""))
    assert glibc.host_version() is None


def test_host_version_is_read_from_cs_gnu_libc_version(monkeypatch):
    monkeypatch.setattr(glibc.os, "confstr", lambda name: "glibc 2.35")
    assert glibc.host_version() == (2, 35)


def test_host_version_falls_back_to_platform_libc_ver(monkeypatch):
    monkeypatch.setattr(glibc.os, "confstr", lambda name: None)
    monkeypatch.setattr(glibc.platform, "libc_ver", lambda: ("glibc", "2.36"))
    assert glibc.host_version() == (2, 36)


def test_auto_falls_back_to_vulkan_below_the_cuda_floor(monkeypatch):
    from hermes_cli.local_runtime.binaries import resolve_backend

    _below(monkeypatch, (2, 35))
    monkeypatch.setattr("pm.store.current_target", lambda: "linux-x64")
    assert resolve_backend("auto", gpu_vendor="NVIDIA", target="linux-x64") == "vulkan"


def test_explicit_cuda_below_the_floor_names_the_working_backend(monkeypatch):
    from hermes_cli.local_runtime.binaries import BinaryResolutionError, resolve_backend

    _below(monkeypatch, (2, 35))
    monkeypatch.setattr("pm.store.current_target", lambda: "linux-x64")
    with pytest.raises(BinaryResolutionError) as caught:
        resolve_backend("cuda", target="linux-x64")
    message = str(caught.value)
    assert "glibc 2.38" in message
    assert "glibc 2.35" in message
    assert "backend: vulkan" in message


def test_install_refuses_a_floor_above_the_host_before_fetching(tmp_path, monkeypatch):
    from pm.install import _install
    from pm.lock import Lockfile
    from pm.store import Store

    _below(monkeypatch, (2, 35))
    monkeypatch.setattr("pm.store.current_target", lambda: "linux-x64")
    lock = Lockfile(tmp_path / "lock.json")
    lock.set_pin("llamacpp-cuda", "11370", {
        "linux-x64": {"url": "https://example.invalid/engine.tar.gz", "sha256": "00" * 32},
    })
    lock.save()
    store = Store(tmp_path / "store")
    with pytest.raises(InstallError) as caught:
        _install(pm.get_package("llamacpp-cuda"), lock, None, store, "linux-x64")
    assert "glibc 2.38" in str(caught.value)
    assert "llamacpp-vulkan" in caught.value.remedy
    assert not list(store.root.rglob("*.tar.gz"))
