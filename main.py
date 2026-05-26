"""
運動計算專案 CLI 入口。

用法：
  python main.py fetch --sport nba --season 2024
  python main.py scrape --sport nba --path /
  python main.py scan --sport nba
  python main.py backtest --sport nba
  python main.py merge-backtest --sport nba --live --save
  python main.py simulate   # 啟動 Streamlit（需另開）
"""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("sportsbet")


def cmd_fetch(args: argparse.Namespace) -> None:
    from sportsbet.data.api_sports import ApiSportsClient

    client = ApiSportsClient()
    df = client.sync_season(args.sport, args.season)
    logger.info("球隊統計 %d 隊", len(df))


def cmd_scrape(args: argparse.Namespace) -> None:
    from sportsbet.data.storage import save_odds
    from sportsbet.data.wanda_scraper import WandaScraper

    scraper = WandaScraper()
    if args.sample:
        df = scraper.load_sample_format()
        save_odds(df, source="sample")
        logger.info("已寫入範例賠率 %d 筆", len(df))
    else:
        df = scraper.scrape_and_save(
            args.sport,  # type: ignore[arg-type]
            use_jbot=args.jbot,
            days_back=args.days_back,
        )
        logger.info("抓取 %d 筆", len(df))


def cmd_scan(args: argparse.Namespace) -> None:
    from sportsbet.monitor.alerts import AlertNotifier
    from sportsbet.monitor.scanner import DailyScanner

    scanner = DailyScanner(args.sport)
    signals = scanner.positive_ev_only(
        wanda_path=args.path,
        use_live_scrape=not args.offline,
    )
    if args.notify and not signals.empty:
        AlertNotifier().notify_signals(signals)
    print(signals.to_string(index=False) if not signals.empty else "無正 EV 訊號")


def cmd_backtest(args: argparse.Namespace) -> None:
    """簡易回測（範例賠率 + 隨機勝負，建議改用 merge-backtest）。"""
    from sportsbet.backtest.engine import BacktestEngine
    from sportsbet.data.storage import load_team_stats
    from sportsbet.models.game_predictor import GamePredictor

    team_stats = load_team_stats(args.sport)
    if team_stats.empty:
        logger.error("請先執行: python main.py fetch --sport %s --season %s", args.sport, args.season)
        return

    from sportsbet.data.wanda_scraper import WandaScraper

    odds = WandaScraper().load_sample_format()
    predictor = GamePredictor(args.sport)  # type: ignore[arg-type]
    signals = predictor.scan_dataframe(team_stats, odds)

    import numpy as np

    rng = np.random.default_rng(0)
    signals["won"] = (rng.random(len(signals)) < signals["model_prob"]).astype(int)
    signals["match_date"] = "2025-01-01"

    engine = BacktestEngine()
    result = engine.run(signals)
    print("=== 回測摘要 ===")
    for k, v in result.summary.items():
        print(f"  {k}: {v}")
    if result.accuracy:
        print("=== 準確率 ===")
        for k, v in result.accuracy.items():
            print(f"  {k}: {v}")


def cmd_merge_backtest(args: argparse.Namespace) -> None:
    import subprocess

    script = ROOT / "scripts" / "merge_backtest.py"
    cmd = [
        sys.executable,
        str(script),
        "--sport",
        args.sport,
        "--market",
        args.market,
        "--odds-phase",
        args.odds_phase,
        "--min-parlay",
        str(args.min_parlay),
    ]
    if args.sample:
        cmd.append("--sample")
    if args.live:
        cmd.append("--live")
    if args.jbot:
        cmd.append("--jbot")
        if args.start:
            cmd.extend(["--start", args.start])
        if args.end:
            cmd.extend(["--end", args.end])
        cmd.extend(["--days-back", str(args.days_back), "--jbot-mode", args.jbot_mode])
    if args.save:
        cmd.append("--save")
    if args.no_backtest:
        cmd.append("--no-backtest")
    subprocess.run(cmd, check=False)


def cmd_refresh_backtest(args: argparse.Namespace) -> None:
    from sportsbet.data.database import SportsDatabase
    from sportsbet.data.db_github_sync import push_database_to_github
    from sportsbet.services.data_refresh import run_full_backtest_refresh

    db = SportsDatabase()
    stats = run_full_backtest_refresh(db, args.sport, sync_api=not args.no_api)
    logger.info("覆盤刷新: %s", stats)
    if args.push:
        push_database_to_github(message=f"chore(data): refresh backtest {args.sport}")


def cmd_push_db(args: argparse.Namespace) -> None:
    from sportsbet.data.db_github_sync import push_database_to_github

    ok = push_database_to_github(force=True)
    if ok:
        logger.info("資料庫已推送至 GitHub")
    else:
        logger.error("推送失敗（請確認 GITHUB_TOKEN）")


def cmd_seed(args: argparse.Namespace) -> None:
    from sportsbet import config
    from sportsbet.data.database import SportsDatabase
    from sportsbet.data.ingestion import MockDataProvider
    from sportsbet.data.player_ingestion import sync_v2_player_data

    db = SportsDatabase()
    provider = MockDataProvider(db)
    provider.fetch_historical_stats(args.sport)
    provider.fetch_daily_schedule(args.sport)
    provider.fetch_odds(args.sport)
    sync_v2_player_data(db, args.sport)
    if not args.no_history:
        days = args.days if args.days is not None else config.BACKTEST_DAYS
        logger.info("產生 %d 天（約 %d 年）回測資料…", days, config.BACKTEST_YEARS)
        df = provider.seed_historical_backtest(args.sport, days=days)
        logger.info("歷史回測 %d 列", len(df))
    logger.info("SQLite: %s", db.db_path)


def cmd_simulate(args: argparse.Namespace) -> None:
    target = ROOT / ("simulator.py" if getattr(args, "legacy", False) else "dashboard.py")
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(target)], check=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="運動計算專案 — NBA/MLB 運彩量化系統")
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="從 API-Sports 抓取賽季資料")
    p_fetch.add_argument("--sport", choices=["nba", "mlb"], default="nba")
    p_fetch.add_argument("--season", type=int, default=2024)
    p_fetch.set_defaults(func=cmd_fetch)

    p_scrape = sub.add_parser("scrape", help="抓取運彩賠率（Blob / 可選 JBot）")
    p_scrape.add_argument("--sport", choices=["nba", "mlb"], default="nba")
    p_scrape.add_argument("--path", default="", help="（相容）未使用，改抓 Blob")
    p_scrape.add_argument("--sample", action="store_true", help="寫入範例資料")
    p_scrape.add_argument("--jbot", action="store_true", help="一併抓取 JBot 歷史")
    p_scrape.add_argument("--days-back", type=int, default=7)
    p_scrape.set_defaults(func=cmd_scrape)

    p_scan = sub.add_parser("scan", help="每日掃描正 EV")
    p_scan.add_argument("--sport", choices=["nba", "mlb"], default="nba")
    p_scan.add_argument("--path", default="")
    p_scan.add_argument("--offline", action="store_true", help="使用範例賠率")
    p_scan.add_argument("--notify", action="store_true", help="推送 Telegram/LINE")
    p_scan.set_defaults(func=cmd_scan)

    p_bt = sub.add_parser("backtest", help="簡易回測（範例資料）")
    p_bt.add_argument("--sport", choices=["nba", "mlb"], default="nba")
    p_bt.add_argument("--season", type=int, default=2024)
    p_bt.set_defaults(func=cmd_backtest)

    p_merge = sub.add_parser("merge-backtest", help="合併賠率+賽果並回測")
    p_merge.add_argument("--sport", choices=["nba", "mlb"], default="nba")
    p_merge.add_argument("--sample", action="store_true")
    p_merge.add_argument("--live", action="store_true", help="抓取運彩 Blob")
    p_merge.add_argument("--jbot", action="store_true", help="抓取 JBot 歷史")
    p_merge.add_argument("--start", default="")
    p_merge.add_argument("--end", default="")
    p_merge.add_argument("--days-back", type=int, default=30)
    p_merge.add_argument("--jbot-mode", default="close", choices=["open", "close", "both", "all"])
    p_merge.add_argument("--market", default="moneyline")
    p_merge.add_argument("--odds-phase", default="close")
    p_merge.add_argument("--min-parlay", type=int, default=1)
    p_merge.add_argument("--save", action="store_true")
    p_merge.add_argument("--no-backtest", action="store_true")
    p_merge.set_defaults(func=cmd_merge_backtest)

    p_refresh = sub.add_parser("refresh-backtest", help="同步歷史賽果並重算全部覆盤")
    p_refresh.add_argument("--sport", choices=["nba", "mlb"], default="nba")
    p_refresh.add_argument("--no-api", action="store_true", help="不呼叫 API-Sports")
    p_refresh.add_argument("--push", action="store_true", help="完成後推送 DB 至 GitHub")
    p_refresh.set_defaults(func=cmd_refresh_backtest)

    p_push = sub.add_parser("push-db", help="推送 data/sportsbet.db 至 GitHub")
    p_push.set_defaults(func=cmd_push_db)

    p_seed = sub.add_parser("seed", help="寫入 MOCK 資料到 SQLite")
    p_seed.add_argument("--sport", choices=["nba", "mlb"], default="nba")
    p_seed.add_argument("--days", type=int, default=None, help="回測天數，預設 3 年")
    p_seed.add_argument("--no-history", action="store_true")
    p_seed.set_defaults(func=cmd_seed)

    p_sim = sub.add_parser("simulate", help="啟動 Streamlit 看板")
    p_sim.add_argument("--legacy", action="store_true", help="使用舊版單頁模擬器")
    p_sim.set_defaults(func=cmd_simulate)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
