"""LINE Notify / Telegram 告警推送。"""
from __future__ import annotations

import logging

import pandas as pd
import requests

from sportsbet import config

logger = logging.getLogger(__name__)


class AlertNotifier:
    def send_telegram(self, message: str) -> bool:
        token = config.TELEGRAM_BOT_TOKEN
        chat_id = config.TELEGRAM_CHAT_ID
        if not token or not chat_id:
            logger.warning("未設定 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID")
            return False
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(url, json={"chat_id": chat_id, "text": message}, timeout=15)
        ok = resp.status_code == 200
        if not ok:
            logger.error("Telegram 發送失敗: %s", resp.text)
        return ok

    def send_line(self, message: str) -> bool:
        token = config.LINE_NOTIFY_TOKEN
        if not token:
            logger.warning("未設定 LINE_NOTIFY_TOKEN")
            return False
        resp = requests.post(
            "https://notify-api.line.me/api/notify",
            headers={"Authorization": f"Bearer {token}"},
            data={"message": message},
            timeout=15,
        )
        ok = resp.status_code == 200
        if not ok:
            logger.error("LINE Notify 發送失敗: %s", resp.text)
        return ok

    def notify_signals(self, signals: pd.DataFrame) -> None:
        if signals.empty:
            return
        lines = ["【運彩正 EV 訊號】"]
        for _, row in signals.iterrows():
            lines.append(
                f"{row.get('home_team')} vs {row.get('away_team')} | "
                f"選 {row.get('selection')} | 賠率 {row.get('odds')} | "
                f"模型 {row.get('model_prob', 0):.1%} | EV {row.get('ev', 0):.2%}"
            )
        msg = "\n".join(lines)
        self.send_telegram(msg)
        self.send_line(msg)
