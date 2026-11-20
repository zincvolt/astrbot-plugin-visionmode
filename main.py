"""Local vision mode: caption images with a small local VL before answering.

State lives in ``data/vision_mode.json``:

    {"mode": "local" | "third_party" | "off", "port": 8085, "model": "Qwen3VL-2B-Instruct"}

``/读图 本地|第三方|关`` switches it. In ``local`` mode the peer plugin captions
the image through the local VL server and injects the text, so the chat model
never receives image payloads. When the VL server is down the caption degrades to
``（读图能力不可用）`` instead of failing the reply.
"""

from __future__ import annotations

import base64
import json
import re
import sys
from pathlib import Path

import httpx
from astrbot.api import logger, star
from astrbot.api.event import AstrMessageEvent, filter

ROOT = Path(r"D:\QQNTBOT")
STATE = ROOT / "data" / "vision_mode.json"

# 权限：优先用 access 统一判定，单拎时自动降级为本地名单（也能用）
sys.path.insert(0, str(ROOT / "apps" / "AstrBot" / "data" / "plugins" / "astrbot_plugin_access"))
try:
    from unified_perm import is_admin as _unified_is_admin
except ImportError:
    _STANDALONE_ADMINS = {"1154487120"}
    def _unified_is_admin(event):  # noqa: F811
        uid = str(event.get_sender_id() or "")
        return uid in _STANDALONE_ADMINS or getattr(event, "role", "") == "admin"

# 本插件自声明指令（单拎时帮助/权限表自动读这里）
DECLARED_COMMANDS = {
    "/读图": ("看当前读图模式", "管理"),
    "/读图 本地": ("图先本地 VL 转文字", "管理"),
    "/读图 第三方": ("图片直接发 DeepSeek", "管理"),
    "/读图 关": ("忽略图片", "管理"),
}


def load_vision_state() -> dict:
    """Return the persisted vision mode state.

    Returns:
        Dict with ``mode``, ``port`` and ``model`` keys.
    """
    if STATE.exists():
        try:
            data = json.loads(STATE.read_text(encoding="utf-8"))
            data.setdefault("mode", "local")
            data.setdefault("port", 8085)
            data.setdefault("model", "Qwen3VL-2B-Instruct")
            return data
        except (json.JSONDecodeError, OSError):
            pass
    return {"mode": "local", "port": 8085, "model": "Qwen3VL-2B-Instruct"}


def save_vision_state(state: dict) -> None:
    """Persist the vision mode state."""
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def local_vl_ready(port: int) -> bool:
    """Check whether the local VL server answers.

    Args:
        port: Local llama-server port.

    Returns:
        True when ``/v1/models`` responds.
    """
    try:
        resp = httpx.get(f"http://127.0.0.1:{port}/v1/models", timeout=3)
        return resp.status_code == 200
    except Exception:  # noqa: BLE001
        return False


async def caption_image(data_url: str, port: int, model: str) -> str | None:
    """Caption one image with the local VL server.

    Args:
        data_url: ``data:image/...;base64,...`` payload or a file path.
        port: Local llama-server port.
        model: Model name to request.

    Returns:
        A short Chinese description, or None when unavailable.
    """
    if data_url.startswith("data:"):
        image_value = data_url
    else:
        try:
            raw = Path(data_url).read_bytes()
        except OSError:
            return None
        image_value = "data:image/png;base64," + base64.b64encode(raw).decode()

    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text",
                 "text": "用中文简短描述这张图：先写图上的文字（如果有），"
                         "再用一句话说画的是什么。总共不超过 80 字。"},
                {"type": "image_url", "image_url": {"url": image_value}},
            ],
        }],
        "max_tokens": 160,
        "temperature": 0.2,
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"http://127.0.0.1:{port}/v1/chat/completions",
                json=payload,
                headers={"Authorization": "Bearer sk-vl-local"},
            )
            resp.raise_for_status()
            data = resp.json()
        text = (data["choices"][0]["message"].get("content") or "").strip()
        return text or None
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[vision-mode] local VL failed: {exc}")
        return None


class Main(star.Star):
    """Switch the vision backend and report its status."""

    def __init__(self, context: star.Context) -> None:
        self.context = context
        logger.info("[vision-mode] ready")

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle(self, event: AstrMessageEvent) -> None:
        """Handle ``/读图`` commands."""
        text = (event.message_str or "").strip()
        if not text:
            return
        raw = ""
        msg_obj = getattr(event, "message_obj", None)
        raw_msg = getattr(msg_obj, "raw_message", None)
        if isinstance(raw_msg, dict):
            raw = str(raw_msg.get("raw_message") or "")
        if not (raw.lstrip().startswith(("/", "／")) or text.startswith(("/", "／"))):
            return
        body = re.sub(r"^\s*[/／]\s*", "", text).strip()
        if not body.startswith("读图"):
            return

        if not _unified_is_admin(event):
            await event.send(event.plain_result("只有管理员能改读图方式"))
            event.stop_event()
            return

        state = load_vision_state()
        arg = body.replace("读图", "").strip().lower()

        if arg in ("", "状态"):
            ready = local_vl_ready(int(state["port"]))
            await event.send(event.plain_result(
                f"读图方式 {state['mode']} · 本地 VL "
                f"{'在线' if ready else '离线'}（端口 {state['port']}）"
            ))
            event.stop_event()
            return

        if arg in ("本地", "local"):
            state["mode"] = "local"
            note = "本地 VL 读图"
        elif arg in ("第三方", "api", "deepseek"):
            state["mode"] = "third_party"
            note = "交给第三方 API 读图"
        elif arg in ("关", "off", "关闭"):
            state["mode"] = "off"
            note = "不读图，直接忽略图片"
        else:
            await event.send(event.plain_result("用法：/读图 本地|第三方|关"))
            event.stop_event()
            return

        save_vision_state(state)
        ready = local_vl_ready(int(state["port"]))
        extra = "" if state["mode"] != "local" else (
            "" if ready else "（本地 VL 当前离线，读图会提示不可用）"
        )
        await event.send(event.plain_result(f"已切换：{note}{extra}"))
        event.stop_event()
