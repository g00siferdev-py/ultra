from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass
class NotifyResult:
    success: bool
    output: str


def send_discord(cfg: dict[str, str], message: str, title: str | None = None) -> NotifyResult:
    webhook = cfg.get("webhook_url", "")
    if not webhook:
        return NotifyResult(success=False, output="Discord webhook_url not configured")

    content = f"**{title}**\n{message}" if title else message

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(webhook, json={"content": content[:2000]})

    if resp.is_success:
        return NotifyResult(success=True, output="Discord notification sent")
    return NotifyResult(success=False, output=f"Discord error: {resp.status_code} {resp.text}")


def send_telegram(cfg: dict[str, str], message: str, title: str | None = None) -> NotifyResult:
    token = cfg.get("bot_token", "")
    chat_id = cfg.get("chat_id", "")
    if not token or not chat_id:
        return NotifyResult(success=False, output="Telegram bot_token/chat_id not configured")

    text = f"*{title}*\n{message}" if title else message

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})

    if resp.is_success:
        return NotifyResult(success=True, output="Telegram notification sent")
    return NotifyResult(success=False, output=f"Telegram error: {resp.status_code} {resp.text}")


def telegram_recent_chats(bot_token: str) -> NotifyResult:
    if not bot_token:
        return NotifyResult(success=False, output="bot_token is required")

    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url)

    if not resp.is_success:
        return NotifyResult(success=False, output=f"Telegram error: {resp.status_code} {resp.text}")

    data = resp.json()
    if not data.get("ok"):
        return NotifyResult(success=False, output=str(data))

    updates = data.get("result") or []
    if not updates:
        return NotifyResult(
            success=False,
            output=(
                "No messages yet. Open Telegram, find your bot, send it 'hello', then run this again."
            ),
        )

    seen: dict[str, str] = {}
    for item in updates:
        msg = item.get("message") or item.get("edited_message")
        if not msg:
            continue
        chat = msg.get("chat") or {}
        cid = chat.get("id")
        if cid is None:
            continue
        label = chat.get("title") or chat.get("username") or chat.get("first_name") or "unknown"
        seen[str(cid)] = str(label)

    lines = [f"chat_id: {cid}  ({name})" for cid, name in seen.items()]
    return NotifyResult(success=True, output="\n".join(lines))
