# src/ai_mesh.py
"""方案 2 · 图转 3D **接口骨架**（批次 1，不接外部服务）。

★ 本批边界（写死在代码行为里，不是文档口号）
    · 四个对外函数 `submit / poll / download / verify` 的**签名与数据结构完整**；
    · **不发起任何真实 HTTP / 网络请求**，也不返回伪造的结果；
    · 缺配置时抛 `MissingAIConfig`（带明确的键名提示），
      配置齐全时抛 `AIServiceNotEnabled`（明确告知本批仅骨架）——
      两条路都**不静默返回 None、不降级到假数据**；
    · `verify()` 是纯本地实现，可离线完整跑通（校验 manifest schema 与 GLB 字节）。

★ 一律不写死、不编造
    端点 / 域名 / 密钥值 / 费用 / 授权结论都不进代码。
    配置只在 `.env.example` 与 `config.yaml` 留**占位键名**（值留空）。

★ ai_glb_manifest.json schema
    {
      "route": "ai_generated",
      "traceable": false,
      "created_at": "<ISO8601 UTC>",
      "glb": {"path": "...", "bytes": 0, "sha256": "..."},
      "source_image": {"sha256": "..."},
      "uv_scope": "glb_internal",
      "strip_aspect": null,
      "boundary_status": "pending"
    }
    `strip_aspect: null` 表示图转 3D 产物的 UV 由 GLB 内部自带，
    **不复用** STRIP_ASPECT 的展开图约定（本批也不做任何形态集扩展）。
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Final

# ---------------------------------------------------------------- 配置键名
# 只是**键名**，不是值；真实值由部署方在 .env / 环境变量里提供，绝不落盘。
ENV_ENDPOINT: Final[str] = "AI3D_ENDPOINT"
ENV_API_KEY: Final[str] = "AI3D_API_KEY"
CONFIG_KEY_HINT: Final[str] = (
    "请在 .env 或环境变量中配置占位键 AI3D_ENDPOINT / AI3D_API_KEY"
    "（键名见 .env.example 与 config.yaml，值不写入仓库）。"
)

# manifest 固定字段（不含任何端点、费用或授权结论）。
MANIFEST_ROUTE: Final[str] = "ai_generated"
MANIFEST_UV_SCOPE: Final[str] = "glb_internal"
MANIFEST_BOUNDARY_STATUS: Final[str] = "pending"
MANIFEST_REQUIRED_KEYS: Final[frozenset[str]] = frozenset((
    "route", "traceable", "created_at", "glb", "source_image",
    "uv_scope", "strip_aspect", "boundary_status",
))
MANIFEST_GLB_KEYS: Final[frozenset[str]] = frozenset(("path", "bytes", "sha256"))


class MissingAIConfig(RuntimeError):
    """缺少图转 3D 服务配置（端点 / 密钥）时抛出，带明确的键名提示。"""


class AIServiceNotEnabled(RuntimeError):
    """本批仅接口骨架、未接入真实服务时抛出。绝不静默降级到假数据。"""


# ---------------------------------------------------------------- 数据结构

@dataclass(frozen=True)
class JobRef:
    """一次图转 3D 提交的引用（本批不做真实提交，仅供接口契约与离线校验）。"""

    job_id: str
    endpoint: str
    submitted_at: str
    image_sha256: str
    route: str = MANIFEST_ROUTE


@dataclass(frozen=True)
class JobStatus:
    """任务轮询结果。state ∈ queued / running / succeeded / failed。"""

    job_id: str
    state: str
    progress: float = 0.0
    detail: str = ""
    checked_at: str = ""


@dataclass(frozen=True)
class VerifyReport:
    """`verify()` 的逐项校验报告。

    Attributes:
        ok: 全部检查项通过。
        glb_sha256: 实际 GLB 字节的 sha256。
        manifest_sha256: manifest 文件的 sha256（传入 dict 时为空串）。
        checks: {检查项: 是否通过}。
        reason: 未通过时的类别说明（不打印任何密钥 / 端点值）。
    """

    ok: bool
    glb_sha256: str
    manifest_sha256: str
    checks: dict[str, bool] = field(default_factory=dict)
    reason: str = ""


# ---------------------------------------------------------------- 内部工具

def _require_config(endpoint: str | None, api_key: str | None) -> tuple[str, str]:
    """解析端点 / 密钥；缺任一项即抛 `MissingAIConfig`。

    值只从参数或环境变量取，**不写死、不落盘、不打印**。
    """
    ep = (endpoint if endpoint is not None else os.environ.get(ENV_ENDPOINT, "")).strip()
    key = (api_key if api_key is not None else os.environ.get(ENV_API_KEY, "")).strip()
    missing: list[str] = []
    if not ep:
        missing.append(ENV_ENDPOINT)
    if not key:
        missing.append(ENV_API_KEY)
    if missing:
        raise MissingAIConfig(
            f"图转 3D 缺少配置键：{'、'.join(missing)}。{CONFIG_KEY_HINT}")
    return ep, key


def _sha256_of(path: Path) -> str:
    """逐字节算 sha256。"""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _utc_now() -> str:
    """ISO8601 UTC 时间戳（秒精度，以 Z 结尾）。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _is_iso8601_utc(value: Any) -> bool:
    """created_at 是否为带 UTC 时区信息的 ISO8601 字符串。"""
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return False
    return dt.tzinfo is not None and dt.utcoffset() == timedelta(0)


def build_job_ref(image_path: str | Path, endpoint: str) -> JobRef:
    """离线构造一个 JobRef，仅用于接口契约与单元测试。

    ★ 不提交任务、不发起请求、不代表真实作业已创建。
    """
    p = Path(image_path)
    return JobRef(
        job_id=f"local-{hashlib.sha256(str(p).encode('utf-8')).hexdigest()[:12]}",
        endpoint=endpoint,
        submitted_at=_utc_now(),
        image_sha256=_sha256_of(p) if p.is_file() else "",
        route=MANIFEST_ROUTE,
    )


# ---------------------------------------------------------------- 四个对外函数

def submit(image_path: str | Path, *, endpoint: str | None = None,
           api_key: str | None = None, timeout_s: float = 30) -> JobRef:
    """提交一张图给图转 3D 服务（**本批仅骨架，不发起请求**）。

    Args:
        image_path: 源图路径，必须存在。
        endpoint: 服务端点；None 时从环境变量 AI3D_ENDPOINT 取。
        api_key: 密钥；None 时从环境变量 AI3D_API_KEY 取。
        timeout_s: 超时秒数（骨架保留参数，批次 2 接入时使用）。

    Returns:
        JobRef。本批配置齐全时也不返回（见下）。

    Raises:
        FileNotFoundError: 源图不存在。
        ValueError: timeout_s 非正。
        MissingAIConfig: 缺端点 / 密钥。
        AIServiceNotEnabled: 配置齐全但本批未接入真实服务。
    """
    p = Path(image_path)
    if not p.is_file():
        raise FileNotFoundError(f"图转 3D 源图不存在：{p}")
    if float(timeout_s) <= 0:
        raise ValueError("timeout_s 必须为正数")
    _require_config(endpoint, api_key)
    raise AIServiceNotEnabled(
        "本批只交付图转 3D 接口骨架，未接入外部服务、不发起任何网络请求；"
        "真实提交留待批次 2。离线契约可用 build_job_ref() 构造 JobRef。")


def poll(job: JobRef, *, interval_s: float = 5,
         max_wait_s: float = 600) -> JobStatus:
    """轮询图转 3D 任务状态（**本批仅骨架，不发起请求**）。

    Args:
        job: submit 返回的 JobRef（或 build_job_ref 构造的离线引用）。
        interval_s: 轮询间隔秒数。
        max_wait_s: 最长等待秒数。

    Raises:
        TypeError: job 不是 JobRef。
        ValueError: 间隔 / 等待时长非法。
        MissingAIConfig: 缺端点 / 密钥。
        AIServiceNotEnabled: 配置齐全但本批未接入真实服务。
    """
    if not isinstance(job, JobRef):
        raise TypeError("poll 需要 JobRef 实例")
    if float(interval_s) <= 0 or float(max_wait_s) < float(interval_s):
        raise ValueError("须满足 interval_s > 0 且 max_wait_s >= interval_s")
    _require_config(None, None)
    raise AIServiceNotEnabled(
        "本批只交付图转 3D 接口骨架，轮询未接入真实服务、不发起任何网络请求。")


def download(job: JobRef, dest: str | Path) -> Path:
    """下载图转 3D 产物到 dest（**本批仅骨架，不发起请求**）。

    Args:
        job: JobRef 实例。
        dest: 目标路径（目录或文件路径）。

    Raises:
        TypeError: job 不是 JobRef。
        MissingAIConfig: 缺端点 / 密钥。
        AIServiceNotEnabled: 配置齐全但本批未接入真实服务。
    """
    if not isinstance(job, JobRef):
        raise TypeError("download 需要 JobRef 实例")
    target = Path(dest)
    if not str(target):
        raise ValueError("dest 不能为空")
    _require_config(None, None)
    raise AIServiceNotEnabled(
        "本批只交付图转 3D 接口骨架，下载未接入真实服务、不发起任何网络请求。")


def build_manifest(glb_path: str | Path, source_image_sha256: str,
                   *, created_at: str | None = None) -> dict[str, Any]:
    """按固定 schema 生成 `ai_glb_manifest.json` 的内容（纯本地，不写盘）。

    Args:
        glb_path: 已产出的 GLB 路径。
        source_image_sha256: 源图 sha256（由图源侧登记，不在此编造）。
        created_at: ISO8601 UTC；None 时取当前 UTC 时间。

    Returns:
        符合 schema 的 dict，可直接 json.dumps 落盘。
    """
    p = Path(glb_path)
    data = p.read_bytes()
    return {
        "route": MANIFEST_ROUTE,
        "traceable": False,
        "created_at": created_at or _utc_now(),
        "glb": {"path": str(p), "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest()},
        "source_image": {"sha256": str(source_image_sha256)},
        "uv_scope": MANIFEST_UV_SCOPE,
        "strip_aspect": None,
        "boundary_status": MANIFEST_BOUNDARY_STATUS,
    }


def verify(glb: str | Path, manifest: str | Path | dict[str, Any]) -> VerifyReport:
    """离线校验 GLB 与 ai_glb_manifest.json 是否自洽（**纯本地，可完整跑通**）。

    检查项：schema 键集合、固定字段值、created_at 为 ISO8601 UTC、
    GLB 字节数 / sha256 / glTF 魔数、source_image.sha256 存在、
    boundary_status 恒 pending。任何一项不满足 → `ok=False` 并给出类别说明。

    Args:
        glb: GLB 文件路径。
        manifest: manifest 文件路径或已解析的 dict。

    Returns:
        VerifyReport。绝不抛出「读不到文件就当通过」的静默成功。
    """
    checks: dict[str, bool] = {}
    reasons: list[str] = []

    if isinstance(manifest, dict):
        m: dict[str, Any] = dict(manifest)
        m_sha = ""
    else:
        mp = Path(manifest)
        if not mp.is_file():
            return VerifyReport(False, "", "", {"manifest_readable": False},
                                "manifest 文件不存在")
        m_sha = _sha256_of(mp)
        try:
            loaded = json.loads(mp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return VerifyReport(False, "", m_sha, {"manifest_readable": False},
                                "manifest 不是合法 JSON")
        m = loaded if isinstance(loaded, dict) else {}
    checks["manifest_readable"] = bool(m)

    checks["schema_keys"] = MANIFEST_REQUIRED_KEYS.issubset(set(m))
    if not checks["schema_keys"]:
        reasons.append("schema 键缺失")

    fixed_ok = (m.get("route") == MANIFEST_ROUTE
                and m.get("traceable") is False
                and m.get("uv_scope") == MANIFEST_UV_SCOPE
                and m.get("strip_aspect") is None
                and m.get("boundary_status") == MANIFEST_BOUNDARY_STATUS)
    checks["schema_fixed_values"] = bool(fixed_ok)
    if not fixed_ok:
        reasons.append("固定字段值不符（route / traceable / uv_scope / "
                       "strip_aspect / boundary_status）")

    checks["created_at_utc"] = _is_iso8601_utc(m.get("created_at"))
    if not checks["created_at_utc"]:
        reasons.append("created_at 不是 ISO8601 UTC")

    glb_node = m.get("glb")
    checks["glb_node_keys"] = (isinstance(glb_node, dict)
                               and MANIFEST_GLB_KEYS.issubset(set(glb_node)))
    if not checks["glb_node_keys"]:
        reasons.append("glb 节点缺 path / bytes / sha256")

    src_node = m.get("source_image")
    src_sha = (src_node.get("sha256") if isinstance(src_node, dict) else None)
    checks["source_image_sha256"] = isinstance(src_sha, str) and bool(src_sha.strip())
    if not checks["source_image_sha256"]:
        reasons.append("source_image.sha256 缺失")

    gp = Path(glb)
    if not gp.is_file():
        checks["glb_readable"] = False
        reasons.append("GLB 文件不存在")
        return VerifyReport(False, "", m_sha, checks, "；".join(reasons))
    data = gp.read_bytes()
    actual_sha = hashlib.sha256(data).hexdigest()
    checks["glb_readable"] = True
    checks["glb_magic"] = data[:4] == b"glTF"
    if not checks["glb_magic"]:
        reasons.append("GLB 魔数不对")
    declared_bytes = glb_node.get("bytes") if isinstance(glb_node, dict) else None
    checks["glb_bytes"] = (isinstance(declared_bytes, int)
                           and declared_bytes == len(data))
    if not checks["glb_bytes"]:
        reasons.append("GLB 字节数与 manifest 不符")
    declared_sha = glb_node.get("sha256") if isinstance(glb_node, dict) else None
    checks["glb_sha256"] = (isinstance(declared_sha, str)
                            and declared_sha == actual_sha)
    if not checks["glb_sha256"]:
        reasons.append("GLB sha256 与 manifest 不符")

    ok = all(checks.values())
    return VerifyReport(ok, actual_sha, m_sha, checks,
                        "" if ok else "；".join(reasons))
