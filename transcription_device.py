"""Whisper device selection with a narrow CUDA-to-CPU fallback."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, replace
from typing import Callable, TypeVar


T = TypeVar("T")


class TranscriptionDeviceError(RuntimeError):
    def __init__(self, message: str, *, gpu_related: bool):
        super().__init__(message)
        self.gpu_related = gpu_related


@dataclass(frozen=True)
class DeviceDecision:
    requested: str
    selected: str
    detail: str
    fallback_used: bool = False


def probe_cuda() -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    name = result.stdout.strip().splitlines()
    return (result.returncode == 0 and bool(name), name[0] if name else result.stderr.strip() or "CUDA unavailable")


def choose_device(requested: str, probe: Callable[[], tuple[bool, str]] = probe_cuda) -> DeviceDecision:
    if requested not in {"auto", "cuda", "cpu"}:
        raise ValueError("device must be auto, cuda or cpu")
    if requested == "cpu":
        return DeviceDecision(requested, "cpu", "CPU selected")
    available, detail = probe()
    if requested == "cuda" and not available:
        raise TranscriptionDeviceError(f"CUDA requested but unavailable: {detail}", gpu_related=True)
    return DeviceDecision(requested, "cuda" if available else "cpu", detail)


def is_gpu_failure(message: str) -> bool:
    lowered = message.lower()
    return any(token in lowered for token in ("cuda", "cudnn", "cublas", "out of memory", "no kernel image", "gpu"))


def transcribe_with_fallback(run: Callable[[str], T], decision: DeviceDecision) -> tuple[T, DeviceDecision]:
    try:
        return run(decision.selected), decision
    except TranscriptionDeviceError as exc:
        if decision.requested == "auto" and decision.selected == "cuda" and exc.gpu_related:
            fallback = replace(decision, selected="cpu", detail=f"CUDA failed; CPU fallback: {exc}", fallback_used=True)
            return run("cpu"), fallback
        raise
