from __future__ import annotations

import logging
from datetime import datetime

import httpx

from .config import TelegramConfig
from .strategy import breakout_delta
from .transfers.service import MatchedTransfer


LOGGER = logging.getLogger(__name__)


class TelegramNotifier:
    """负责把突破提醒和链上转账发送到 Telegram。"""

    TRANSFER_SUMMARY_MAX_CHARS = 3500
    TRANSFER_SUMMARY_MAX_MATCHES = 50

    def __init__(self, config: TelegramConfig, timeout: float = 20.0) -> None:
        self.config = config
        self.timeout = timeout

    def send_breakout_summary(self, breakouts: list[dict], breakout_time: datetime) -> bool:
        """发送突破名单汇总。"""
        if not breakouts:
            return True

        new_breakouts = [item for item in breakouts if item.get("status") == "新突破"]
        existing_breakouts = [item for item in breakouts if item.get("status") != "新突破"]
        ordinal_by_symbol = self._build_breakout_ordinals(breakouts)

        lines = [f"[突破名单] {len(breakouts)}个", ""]

        if new_breakouts:
            lines.append("新突破")
            for item in new_breakouts:
                lines.append(self._format_breakout_line(item, ordinal=ordinal_by_symbol.get(str(item["symbol"]))))
            lines.append("")

        if existing_breakouts:
            lines.append("今日已突破")
            for item in existing_breakouts:
                lines.append(self._format_breakout_line(item, ordinal=ordinal_by_symbol.get(str(item["symbol"]))))
            lines.append("")

        text = "\n".join(lines).strip()
        return self._send_text(text, f"{len(breakouts)} breakout symbols")

    def _format_breakout_line(self, item: dict, ordinal: int | None = None) -> str:
        _, percent = breakout_delta(item["current_price"], item["threshold"])
        prefix = "" if ordinal is None else f"[第{ordinal}个突破] "
        return f"{prefix}{item['symbol']}  {item['current_price']:g} > {item['threshold']:g}  ({percent:+.2f}%)"

    def _build_breakout_ordinals(self, breakouts: list[dict]) -> dict[str, int]:
        ordered = sorted(
            breakouts,
            key=lambda item: (str(item.get("breakout_time", "")), str(item.get("symbol", ""))),
        )
        return {str(item["symbol"]): index for index, item in enumerate(ordered, start=1)}

    def send_transfer_summary(self, matches: list[MatchedTransfer], observed_at: datetime) -> bool:
        """发送链上大额转账汇总。"""
        if not matches:
            return True

        limited_matches = matches[: self.TRANSFER_SUMMARY_MAX_MATCHES]
        omitted_count = len(matches) - len(limited_matches)
        sections = [self._format_transfer_section(match) for match in limited_matches]
        chunks = self._chunk_transfer_sections(
            sections=sections,
            total_matches=len(matches),
            observed_at=observed_at,
            omitted_count=omitted_count,
        )
        ok = True
        for index, chunk in enumerate(chunks, start=1):
            context = f"{len(matches)} transfer matches chunk {index}/{len(chunks)}"
            ok = self._send_text(chunk, context) and ok
        return ok

    def _format_transfer_section(self, match: MatchedTransfer) -> str:
        """格式化单条转账记录。"""
        event = match.event
        amount_text = f"{event.amount:g} {event.asset}"
        usd_text = "" if event.usd_value is None else f" (${event.usd_value:,.0f})"
        from_text = event.from_label or event.from_address
        to_text = event.to_label or event.to_address
        return "\n".join(
            [
                f"{event.chain} | {amount_text}{usd_text}",
                f"{from_text} -> {to_text}",
                f"tx: {event.tx_hash}",
            ]
        )

    def _chunk_transfer_sections(
        self,
        sections: list[str],
        total_matches: int,
        observed_at: datetime,
        omitted_count: int,
    ) -> list[str]:
        """按 Telegram 长度限制拆分转账消息。"""
        header = [f"[链上大额转账] {total_matches}笔", f"时间: {observed_at.strftime('%Y-%m-%d %H:%M:%S %Z')}"]
        suffix = [] if omitted_count <= 0 else ["", f"其余 {omitted_count} 笔已省略"]
        chunks: list[str] = []
        current_lines = header[:]

        for section in sections:
            candidate_lines = current_lines + ["", section]
            candidate_text = "\n".join(candidate_lines + suffix).strip()
            if len(candidate_text) > self.TRANSFER_SUMMARY_MAX_CHARS and len(current_lines) > len(header):
                chunks.append("\n".join(current_lines).strip())
                current_lines = header + ["", section]
            else:
                current_lines = candidate_lines

        final_text = "\n".join(current_lines + suffix).strip()
        if not chunks:
            return [final_text]

        chunks.append(final_text)
        total_chunks = len(chunks)
        return [f"[{index}/{total_chunks}]\n{chunk}" for index, chunk in enumerate(chunks, start=1)]

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
