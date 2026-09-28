"""Local Go executable bridge; settings travel via stdin, never shell arguments."""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def executable():
    configured = os.environ.get("BANGUMIKOMGA_CORE", "").strip()
    if configured == "off":
        return None
    candidate = Path(configured) if configured else ROOT / "bin" / (
        "bangumikomga-core.exe" if os.name == "nt" else "bangumikomga-core")
    if candidate.is_file():
        return candidate
    if configured:
        raise RuntimeError("配置的 Go 核心文件不存在")
    return None


def archive_request(action, folder, **values):
    return core_request("archive." + action, {"folder": str(Path(folder).resolve()), **values},
                        dict if action == "get" else list, timeout=25)


def core_request(action, values, expected=dict, timeout=185):
    binary = executable()
    if binary is None:
        return None
    request = {"protocol": 1, "action": action, **values}
    try:
        result = subprocess.run(
            [str(binary)], input=json.dumps(request, ensure_ascii=False),
            capture_output=True, encoding="utf-8", timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            check=False,
        )
        response = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        raise RuntimeError("Go 核心调用失败") from exc
    if not isinstance(response, dict):
        raise RuntimeError("Go 核心响应格式错误")
    if result.returncode or response.get("error") or response.get("protocol") != 1:
        raise RuntimeError("Go 核心错误：" + str(response.get("error", "协议不兼容")))
    data = response.get("data")
    if not isinstance(data, expected):
        raise RuntimeError("Go 核心返回数据类型不正确")
    return data
