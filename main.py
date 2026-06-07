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
    from sportsbet.data.wanda_scraper import WandaScraper

    scraper = WandaScraper()
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
    signals = scanner.positive_ev_only()
    if args.notify and not signals.empty:
        AlertNotifier().notify_signals(signals)
    print(signals.to_string(index=False) if not signals.empty else "無正 EV 訊號")


def cmd_sync(args: argparse.Namespace) -> None:
    from sportsbet import config
    from sportsbet.data.database import SportsDatabase
    from sportsbet.data.db_github_sync import persist_database_after_sync
    from sportsbet.data.orchestrator import DataOrchestrator

    db = SportsDatabase()
    orch = DataOrchestrator(db)
    sports = ["nba", "mlb"] if args.sport == "all" else [args.sport]

    for sp in sports:
        if args.mode == "daily":
            stats = orch.sync_daily(sp, days_ahead=args.days, force_players=args.force)  # type: ignore[arg-type]
        elif args.mode == "backtest":
            stats = (
                orch.sync_backtest_full(sp)
                if args.full
                else orch.sync_backtest_incremental(sp)
            )
        elif args.mode == "games":
            stats = {
                "days": orch.sync_games(
                    sp,  # type: ignore[arg-type]
                    incremental=args.incremental,
                )
            }
        elif args.mode == "odds":
            stats = {"days": orch.sync_odds(sp, replace=True)}  # type: ignore[arg-type]
        elif args.mode == "live":
            from sportsbet.services.live_sync import LiveSyncService

            stats = LiveSyncService(db).sync_live(sp)  # type: ignore[arg-type]
        elif args.mode == "players":
            stats = orch.sync_players(sp, days_lineup=args.days, force=True)  # type: ignore[arg-type]
        else:
            raise RuntimeError(f"未知 sync 模式: {args.mode}")
        logger.info("sync %s %s: %s", sp, args.mode, stats)

    if args.push or config.GITHUB_AUTO_PUSH:
        persist_database_after_sync(message=f"chore(data): sync {args.mode} {args.sport}", db=db)


def cmd_watch(args: argparse.Namespace) -> None:
    from sportsbet import config as app_config
    from sportsbet.services.live_sync import run_watch_loop

    sports = ["nba", "mlb"] if args.sport == "all" else [args.sport]
    push = app_config.WATCH_PUSH_GITHUB if not getattr(args, "no_push", False) else False
    run_watch_loop(
        sports=sports,  # type: ignore[arg-type]
        interval_sec=args.interval or None,
        push_github=push,
    )


def cmd_backtest(args: argparse.Namespace) -> None:
    raise RuntimeError("已停用範例回測（MOCK）。請使用 `refresh-backtest` 同步真實 API 資料。")


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
    from sportsbet.data.db_github_sync import persist_database_after_sync
    from sportsbet.services.data_refresh import (
        run_full_backtest_refresh,
        run_incremental_backtest_refresh,
    )

    db = SportsDatabase()
    if args.full:
        stats = run_full_backtest_refresh(db, args.sport, sync_api=not args.no_api)
    else:
        stats = run_incremental_backtest_refresh(db, args.sport, sync_api=not args.no_api)
    logger.info("覆盤刷新: %s", stats)
    if args.push:
        persist_database_after_sync(message=f"chore(data): refresh backtest {args.sport}", db=db)


def cmd_scrape_playsport(args: argparse.Namespace) -> None:
    from sportsbet.data.database import SportsDatabase
    from sportsbet.data.playsport_scraper import PlaySportScraper

    db = SportsDatabase()
    scraper = PlaySportScraper()
    if args.team_id:
        df = scraper.sync_team_to_database(db, args.team_id, args.sport)
    else:
        df = scraper.sync_sport(db, args.sport, max_teams=args.max_teams)
    logger.info("玩運彩同步 %d 筆", len(df))


def cmd_push_db(args: argparse.Namespace) -> None:
    from sportsbet.data.db_github_sync import push_database_to_github

    ok = push_database_to_github(force=True)
    if ok.ok:
        logger.info("資料庫已推送至 GitHub")
    else:
        logger.error("推送失敗：%s", ok.detail)


def cmd_simulate(args: argparse.Namespace) -> None:
    target = ROOT / ("simulator.py" if getattr(args, "legacy", False) else "dashboard.py")
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(target)], check=False)


def cmd_optimize(args: argparse.Namespace) -> None:
    from scripts.bet_optimizer_cli import run_cli

    game_ids = [int(x) for x in args.game_id] if args.game_id else None
    run_cli(
        from_db=args.from_db,
        sport=args.sport,
        days=args.days,
        game_ids=game_ids,
        total_stake=args.stake,
        min_ev=args.min_ev,
    )


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
    p_scrape.add_argument("--jbot", action="store_true", help="一併抓取 JBot 歷史")
    p_scrape.add_argument("--days-back", type=int, default=7)
    p_scrape.set_defaults(func=cmd_scrape)

    p_scan = sub.add_parser("scan", help="每日掃描正 EV（真實盤口）")
    p_scan.add_argument("--sport", choices=["nba", "mlb"], default="nba")
    p_scan.add_argument("--notify", action="store_true", help="推送 Telegram/LINE")
    p_scan.set_defaults(func=cmd_scan)

    p_sync = sub.add_parser("sync", help="資料同步（NBA/MLB 真實 API）")
    p_sync.add_argument(
        "--mode",
        choices=["daily", "live", "backtest", "games", "odds", "players"],
        default="daily",
    )
    p_sync.add_argument("--sport", choices=["nba", "mlb", "all"], default="all")
    p_sync.add_argument("--days", type=int, default=7, help="daily/players 前瞻天數")
    p_sync.add_argument("--full", action="store_true", help="backtest 完整重算")
    p_sync.add_argument("--incremental", action="store_true", help="games 增量模式")
    p_sync.add_argument("--force", action="store_true", help="daily 強制重抓球員統計")
    p_sync.add_argument("--push", action="store_true", help="完成後推送 DB 至 GitHub")
    p_sync.set_defaults(func=cmd_sync)

    p_watch = sub.add_parser("watch", help="背景即時同步（常駐，供看板即時觀察）")
    p_watch.add_argument("--sport", choices=["nba", "mlb", "all"], default="all")
    p_watch.add_argument("--interval", type=int, default=0, help="秒；0=使用 LIVE_SYNC_INTERVAL_SEC")
    p_watch.add_argument("--no-push", action="store_true", help="關閉每次同步後推送 DB")
    p_watch.set_defaults(func=cmd_watch)

    p_bt = sub.add_parser("backtest", help="（已停用）請改用 refresh-backtest")
    p_bt.add_argument("--sport", choices=["nba", "mlb"], default="nba")
    p_bt.add_argument("--season", type=int, default=2024)
    p_bt.set_defaults(func=cmd_backtest)

    p_merge = sub.add_parser("merge-backtest", help="合併賠率+賽果並回測")
    p_merge.add_argument("--sport", choices=["nba", "mlb"], default="nba")
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

    p_refresh = sub.add_parser("refresh-backtest", help="增量同步歷史賽果並補齊覆盤（預設）")
    p_refresh.add_argument("--sport", choices=["nba", "mlb"], default="nba")
    p_refresh.add_argument("--no-api", action="store_true", help="不呼叫 API-Sports")
    p_refresh.add_argument("--full", action="store_true", help="強制重算全部覆盤（較慢）")
    p_refresh.add_argument("--push", action="store_true", help="完成後推送 DB 至 GitHub")
    p_refresh.set_defaults(func=cmd_refresh_backtest)

    p_ps = sub.add_parser("scrape-playsport", help="抓取玩運彩球隊歷史賽事")
    p_ps.add_argument("--sport", choices=["nba", "mlb"], default="nba")
    p_ps.add_argument("--team-id", type=int, default=0, help="單隊 teamid（如雷霆=53）")
    p_ps.add_argument("--max-teams", type=int, default=30)
    p_ps.set_defaults(func=cmd_scrape_playsport)

    p_push = sub.add_parser("push-db", help="推送 data/sportsbet.db 至 GitHub")
    p_push.set_defaults(func=cmd_push_db)

    p_sim = sub.add_parser("simulate", help="啟動 Streamlit 看板")
    p_sim.add_argument("--legacy", action="store_true", help="使用舊版單頁模擬器")
    p_sim.set_defaults(func=cmd_simulate)

    p_opt = sub.add_parser("optimize", help="全玩法 EV 優化 / 對沖 / 串關 CLI")
    p_opt.add_argument("--from-db", action="store_true", help="從 DB 自動讀取 preferred 盤口")
    p_opt.add_argument("--sport", choices=["nba", "mlb"], default="nba")
    p_opt.add_argument("--days", type=int, default=7, help="--from-db 前瞻天數")
    p_opt.add_argument("--game-id", type=int, action="append", dest="game_id", help="指定 game_id（可重複）")
    p_opt.add_argument("--stake", type=float, default=None, help="總注碼（元）")
    p_opt.add_argument("--min-ev", type=float, default=None, help="最低 EV 門檻")
    p_opt.set_defaults(func=cmd_optimize)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
