from __future__ import annotations

import logging
from datetime import datetime

import httpx

from .config import TelegramConfig
from .strategy import breakout_delta


LOGGER = logging.getLogger(__name__)


class TelegramNotifier:
    """负责把突破提醒发送到 Telegram。"""

    BREAKOUT_SUMMARY_MAX_CHARS = 3500

    def __init__(self, config: TelegramConfig, timeout: float = 20.0) -> None:
        self.config = config
        self.timeout = timeout

    def send_breakout_summary(self, breakouts: list[dict], breakout_time: datetime) -> bool:
        """发送突破名单汇总。"""
        if not breakouts:
            return True

        new_breakouts = [item for item in breakouts if item.get("status") == "新突破"]
        existing_breakouts = [item for item in breakouts if item.get("status") != "新突破"]
        destinations: list[tuple[str, list[tuple[str, list[dict]]]]] = []
        for heading, items in [("新突破", new_breakouts), ("今日已突破", existing_breakouts)]:
            if not items:
                continue
            chat_id = self.config.chat_id_for_breakout_status(heading)
            for destination_chat_id, sections in destinations:
                if destination_chat_id == chat_id:
                    sections.append((heading, items))
                    break
            else:
                destinations.append((chat_id, [(heading, items)]))

        ok = True
        for chat_id, sections in destinations:
            total_breakouts = sum(len(items) for _, items in sections)
            chunks = self._chunk_breakout_sections(
                total_breakouts=total_breakouts,
                sections=sections,
            )
            headings = "+".join(heading for heading, _ in sections)
            for index, chunk in enumerate(chunks, start=1):
                context = f"{headings} {total_breakouts} breakout symbols chunk {index}/{len(chunks)}"
                ok = self._send_text(chunk, context, chat_id=chat_id) and ok
        return ok

    def _format_breakout_line(self, item: dict) -> str:
        _, percent = breakout_delta(item["current_price"], item["threshold"])
        ordinal = item.get("breakout_ordinal")
        prefix = "" if ordinal is None else f"[第{int(ordinal)}个突破] "
        return f"{prefix}{item['symbol']}  {item['current_price']:g} > {item['threshold']:g}  ({percent:+.2f}%)"

    def _chunk_breakout_sections(
        self,
        total_breakouts: int,
        sections: list[tuple[str, list[dict]]],
    ) -> list[str]:
        """按 Telegram 长度限制拆分突破名单，必要时重复分块标题。"""
        header = [f"[突破名单] {total_breakouts}个"]
        chunks: list[str] = []
        current_lines = header[:]
        current_section: str | None = None

        for heading, items in sections:
            if not items:
                continue
            for item in items:
                addition: list[str] = []
                if current_section != heading:
                    if len(current_lines) > len(header):
                        addition.append("")
                    addition.append(heading)
                addition.append(self._format_breakout_line(item))
                candidate = "\n".join(current_lines + addition).strip()
                if len(candidate) > self.BREAKOUT_SUMMARY_MAX_CHARS and len(current_lines) > len(header):
                    chunks.append("\n".join(current_lines).strip())
                    current_lines = header + ["", heading, self._format_breakout_line(item)]
                else:
                    current_lines.extend(addition)
                current_section = heading

        final_text = "\n".join(current_lines).strip()
        if not chunks:
            return [final_text]

        chunks.append(final_text)
        total_chunks = len(chunks)
        return [f"[{index}/{total_chunks}]\n{chunk}" for index, chunk in enumerate(chunks, start=1)]

    def _send_text(self, text: str, context: str, chat_id: str) -> bool:
        """发送一条 Telegram 文本消息。"""
        if not chat_id:
            LOGGER.error("Telegram chat_id is missing for %s", context)
            return False

        url = f"https://api.telegram.org/bot{self.config.bot_token}/sendMessage"
        try:
            response = httpx.post(
                url,
                json={"chat_id": chat_id, "text": text},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            ok = bool(payload.get("ok", False))
            if not ok:
                LOGGER.error("Telegram returned non-ok response for %s: %s", context, payload)
            else:
                LOGGER.info("Telegram alert sent for %s chars=%d", context, len(text))
            return ok
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:500]
            LOGGER.error(
                "Telegram request failed for %s status=%d body=%s",
                context,
                exc.response.status_code,
                body,
            )
            LOGGER.exception("Failed to send Telegram alert for %s", context)
            return False
        except Exception:
            LOGGER.exception("Failed to send Telegram alert for %s", context)
            return False
