from __future__ import annotations

import logging
from datetime import datetime

import httpx

from .config import TelegramConfig
from .strategy import breakout_delta


LOGGER = logging.getLogger(__name__)


class TelegramNotifier:
    """负责把突破提醒发送到 Telegram 聊天。"""

    def __init__(self, config: TelegramConfig, timeout: float = 20.0) -> None:
        self.config = config
        self.timeout = timeout

    def send_breakout_summary(self, breakouts: list[dict], breakout_time: datetime) -> bool:
        """发送一条包含今日全部已突破币种的汇总消息。"""
        if not breakouts:
            return True

        new_breakouts = [item for item in breakouts if item.get("status") == "新突破"]
        existing_breakouts = [item for item in breakouts if item.get("status") != "新突破"]

        lines = [f"[突破名单] {len(breakouts)}个", ""]

        if new_breakouts:
            lines.append("新突破")
            for item in new_breakouts:
                delta, percent = breakout_delta(item["current_price"], item["threshold"])
                lines.append(
                    f"{item['symbol']}  {item['current_price']:g} > {item['threshold']:g}  (+{percent:.2f}%)"
                )
            lines.append("")

        if existing_breakouts:
            lines.append("今日已突破")
            for item in existing_breakouts:
                delta, percent = breakout_delta(item["current_price"], item["threshold"])
                lines.append(
                    f"{item['symbol']}  {item['current_price']:g} > {item['threshold']:g}  (+{percent:.2f}%)"
                )
            lines.append("")

        text = "\n".join(lines).strip()
        return self._send_text(text, f"{len(breakouts)} breakout symbols")

    def _send_text(self, text: str, context: str) -> bool:
        """发送一条 Telegram 文本消息。"""
        url = f"https://api.telegram.org/bot{self.config.bot_token}/sendMessage"
        try:
            response = httpx.post(
                url,
                json={"chat_id": self.config.chat_id, "text": text},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            ok = bool(payload.get("ok", False))
            if not ok:
                LOGGER.error("Telegram returned non-ok response for %s: %s", context, payload)
            return ok
        except Exception:
            LOGGER.exception("Failed to send Telegram alert for %s", context)
            return False
