"""驗證：資料真實性、公式正確性、校準偏差、前視偏差。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd

from sportsbet import analytics
from sportsbet.backtest.metrics import accuracy_report
from sportsbet.data.database import SportsDatabase
from sportsbet.evaluation.ev_report import build_ev_backtest_report
from sportsbet.models.analytics_engine import AnalyticsEngine


def main() -> None:
    db = SportsDatabase()

    print("=" * 60)
    print("1. 資料真實性檢查")
    print("=" * 60)

    with db.connection() as conn:
        for sport in ("nba", "mlb"):
            g = pd.read_sql_query(
                """
                SELECT COUNT(*) AS n, MIN(match_date) AS d0, MAX(match_date) AS d1
                FROM games WHERE sport = ?
                """,
                conn,
                params=(sport,),
            ).iloc[0]
            scored = conn.execute(
                "SELECT COUNT(*) FROM games WHERE sport = ? AND home_score IS NOT NULL",
                (sport,),
            ).fetchone()[0]
            fc = conn.execute(
                """
                SELECT COUNT(*) FROM game_forecasts f
                JOIN games g ON g.id = f.game_id WHERE f.sport = ?
                """,
                (sport,),
            ).fetchone()[0]
            pred = conn.execute(
                """
                SELECT COUNT(*) FROM predictions p
                JOIN games g ON g.id = p.game_id WHERE g.sport = ?
                """,
                (sport,),
            ).fetchone()[0]
            odds_n = conn.execute(
                "SELECT COUNT(*) FROM odds o JOIN games g ON g.id = o.game_id WHERE g.sport = ?",
                (sport,),
            ).fetchone()[0]
            sources = pd.read_sql_query(
                """
                SELECT o.bookmaker, COUNT(*) AS n
                FROM odds o JOIN games g ON g.id = o.game_id
                WHERE g.sport = ? GROUP BY o.bookmaker
                """,
                conn,
                params=(sport,),
            )
            print(
                f"\n[{sport.upper()}] 賽事={g['n']} ({g['d0']}~{g['d1']}) "
                f"有比分={scored} forecast={fc} predictions={pred} odds={odds_n}"
            )
            print(sources.to_string(index=False))

        mock_n = conn.execute(
            """
            SELECT COUNT(*) FROM games
            WHERE home_team LIKE '%Mock%' OR away_team LIKE '%Mock%'
            """,
        ).fetchone()[0]
        print(f"\nMock 隊名場次: {mock_n}")

        print("\n最近 3 場 NBA 賽果:")
        print(
            pd.read_sql_query(
                """
                SELECT match_date, home_team, away_team, home_score, away_score
                FROM games WHERE sport = 'nba' AND home_score IS NOT NULL
                ORDER BY match_date DESC LIMIT 3
                """,
                conn,
            ).to_string(index=False)
        )

        print("\n賽事狀態分布 (NBA):")
        print(
            pd.read_sql_query(
                """
                SELECT status, COUNT(*) AS n FROM games WHERE sport = 'nba'
                GROUP BY status ORDER BY n DESC
                """,
                conn,
            ).to_string(index=False)
        )
        print("\n比分品質 (NBA):")
        print(
            pd.read_sql_query(
                """
                SELECT
                  CASE
                    WHEN home_score IS NULL THEN 'null'
                    WHEN home_score = 0 AND away_score = 0 THEN '0-0'
                    ELSE 'has_points'
                  END AS score_type,
                  COUNT(*) AS n
                FROM games WHERE sport = 'nba' GROUP BY score_type
                """,
                conn,
            ).to_string(index=False)
        )
        real_final = conn.execute(
            """
            SELECT COUNT(*) FROM games
            WHERE sport = 'nba' AND status = 'final'
              AND home_score IS NOT NULL AND (home_score + away_score) > 0
            """,
        ).fetchone()[0]
        ts = conn.execute("SELECT COUNT(*) FROM team_stats WHERE sport = 'nba'").fetchone()[0]
        print(f"\n有效 final 場次 (有得分): {real_final} | team_stats 列數: {ts}")

    print("\n" + "=" * 60)
    print("2. 公式自檢")
    print("=" * 60)

    h, _ = analytics.matchup_win_prob(0.6, 0.4, 0.03)
    manual_denom = 0.63 + 0.4 - 2 * 0.63 * 0.4
    manual = (0.63 - 0.63 * 0.4) / manual_denom
    print(f"Log5: code={h:.6f} manual={manual:.6f} OK={abs(h - manual) < 1e-9}")

    ev = analytics.expected_value(0.55, 1.75)
    print(f"EV(55%,1.75)={ev:.4f} expected={0.55 * 1.75 - 1:.4f}")
    print(f"Breakeven 1.75={analytics.breakeven_win_rate(1.75):.4f} expected={1/1.75:.4f}")

    print("\n" + "=" * 60)
    print("3. 回測校準 & EV")
    print("=" * 60)

    for sport in ("nba", "mlb"):
        df = db.get_backtest_frame(sport)
        if df.empty:
            print(f"\n[{sport}] 無回測資料")
            continue
        df = df[df["market"] == "moneyline"] if "market" in df.columns else df
        if df.empty:
            print(f"\n[{sport}] 無 moneyline 回測資料")
            continue
        df = df.copy()
        df["model_prob"] = df["model_prob"].astype(float).clip(0.001, 0.999)
        rep = build_ev_backtest_report(df)
        acc = accuracy_report(df, "model_prob", "won")
        print(f"\n[{sport.upper()}] {rep.summary_text}")
        gap = rep.avg_model_prob - rep.actual_win_rate
        bias = "高估" if gap > 0.03 else ("低估" if gap < -0.03 else "尚可")
        print(
            f"  整體偏差: {gap:+.1%} ({bias}) | Brier={rep.brier_score:.4f} | "
            f"校準={rep.pass_calibration} ROI={rep.pass_roi} EV={rep.pass_ev_threshold}"
        )
        if acc:
            print(f"  metrics: {acc}")
        if not rep.by_prob_bucket.empty:
            print("  分桶校準 (n>=5):")
            for _, r in rep.by_prob_bucket.iterrows():
                if r["count"] >= 5:
                    g2 = r["predicted"] - r["win_rate"]
                    b2 = "高估" if g2 > 0.03 else ("低估" if g2 < -0.03 else "尚可")
                    print(
                        f"    {r['prob_bucket']}: n={int(r['count'])} "
                        f"預測={r['predicted']:.1%} 實際={r['win_rate']:.1%} ({b2})"
                    )

    print("\n" + "=" * 60)
    print("4. 前視偏差檢測")
    print("=" * 60)

    with db.connection() as conn:
        games_df = pd.read_sql_query(
            """
            SELECT id, match_date, home_team, away_team, home_score, away_score
            FROM games WHERE sport = 'nba' AND home_score IS NOT NULL
            ORDER BY match_date
            """,
            conn,
        )

    if len(games_df) >= 10:
        early = games_df.iloc[min(20, len(games_df) - 1)]
        d = str(early["match_date"])[:10]
        ht, at = early["home_team"], early["away_team"]
        stats_full = db.get_team_stats("nba").set_index("team")
        prior = games_df[games_df["match_date"].astype(str).str[:10] < d]

        def team_rs_ra(team: str) -> tuple[float, float, int]:
            rows = prior[(prior.home_team == team) | (prior.away_team == team)]
            rs = ra = g = 0
            for _, r in rows.iterrows():
                if r.home_team == team:
                    rs += int(r.home_score)
                    ra += int(r.away_score)
                else:
                    rs += int(r.away_score)
                    ra += int(r.home_score)
                g += 1
            return (rs / g if g else 110.0, ra / g if g else 110.0, g)

        eng = AnalyticsEngine("nba")
        hrs, hra, hg = team_rs_ra(ht)
        ars, ara, ag = team_rs_ra(at)
        pit_h = eng.team_win_pct(hrs, hra, hg)
        pit_a = eng.team_win_pct(ars, ara, ag)
        pit_p, _ = analytics.matchup_win_prob(pit_h, pit_a)

        if ht in stats_full.index and at in stats_full.index:
            h, a = stats_full.loc[ht], stats_full.loc[at]
            full_h = eng.team_win_pct(
                float(h["rs_per_game"]), float(h["ra_per_game"]), int(h.get("games", 0))
            )
            full_a = eng.team_win_pct(
                float(a["rs_per_game"]), float(a["ra_per_game"]), int(a.get("games", 0))
            )
            full_p, _ = analytics.matchup_win_prob(full_h, full_a)

            with db.connection() as conn:
                row = conn.execute(
                    "SELECT home_win_prob FROM game_forecasts WHERE game_id = ?",
                    (int(early["id"]),),
                ).fetchone()
            stored_p = float(row["home_win_prob"]) if row else None

            print(f"早期場次 {d}: {ht} vs {at}")
            print(f"  賽前累積: 主{hg}客{ag} | 賽前 Log5={pit_p:.1%} | 全季 Log5={full_p:.1%}")
            if stored_p is not None:
                dist_pit = abs(stored_p - pit_p)
                dist_full = abs(stored_p - full_p)
                print(f"  DB forecast={stored_p:.1%} | 距賽前={dist_pit:.1%} 距全季={dist_full:.1%}")
                if dist_pit < dist_full - 0.02:
                    print("  ✓ 存儲值接近賽前 stats（前視偏差已修正）")
                elif dist_full < dist_pit - 0.02:
                    print("  ⚠ 存儲值更接近全季 stats → 回測可能有前視偏差")
                else:
                    print("  存儲值介於賽前/全季之間")

    print("\n" + "=" * 60)
    print("5. EV 重算一致性")
    print("=" * 60)

    with db.connection() as conn:
        chk = pd.read_sql_query(
            """
            SELECT p.model_prob, p.ev, o.odds
            FROM predictions p
            JOIN odds o ON o.game_id = p.game_id
                AND p.market = o.market AND p.selection = o.selection
            JOIN games g ON g.id = p.game_id
            WHERE g.sport = 'nba'
            LIMIT 500
            """,
            conn,
        )
    if not chk.empty:
        chk["ev_recalc"] = chk.apply(
            lambda r: analytics.expected_value(float(r["model_prob"]), float(r["odds"])),
            axis=1,
        )
        chk["ev_diff"] = (chk["ev"] - chk["ev_recalc"]).abs()
        bad = int((chk["ev_diff"] > 0.0001).sum())
        print(f"NBA: {len(chk)} 筆, EV 不一致 {bad} 筆, max_diff={chk['ev_diff'].max():.6f}")
    else:
        print("predictions 表為空 — 無法驗證 EV 儲存一致性")

    print("\n" + "=" * 60)
    print("6. 即時賽前 Log5 校準（不依賴 game_forecasts）")
    print("=" * 60)

    with db.connection() as conn:
        games = pd.read_sql_query(
            """
            SELECT id, match_date, home_team, away_team, home_score, away_score, status
            FROM games WHERE sport = 'nba' AND status = 'final'
              AND home_score IS NOT NULL AND (home_score + away_score) > 0
            ORDER BY match_date
            """,
            conn,
        )
        odds = pd.read_sql_query(
            """
            SELECT o.game_id, o.market, o.selection, o.odds
            FROM odds o JOIN games g ON g.id = o.game_id
            WHERE g.sport = 'nba' AND o.market = 'moneyline'
            """,
            conn,
        )

    if games.empty or odds.empty:
        print("有效 final 或 moneyline 賠率不足，跳過")
    else:
        eng = AnalyticsEngine("nba")
        cum: dict[str, list[tuple[int, int]]] = {}
        rows = []

        def rs_ra(team: str) -> tuple[float, float, int]:
            hist = cum.get(team, [])
            g = len(hist)
            if g == 0:
                return 110.0, 110.0, 0
            rs = sum(x[0] for x in hist) / g
            ra = sum(x[1] for x in hist) / g
            return rs, ra, g

        for _, g in games.iterrows():
            gid = int(g["id"])
            ht, at = g["home_team"], g["away_team"]
            hrs, hra, hg = rs_ra(ht)
            ars, ara, ag = rs_ra(at)
            if hg >= 3 and ag >= 3:
                ph = eng.team_win_pct(hrs, hra, hg)
                pa = eng.team_win_pct(ars, ara, ag)
                p_home, _ = analytics.matchup_win_prob(ph, pa)
                o = odds[(odds.game_id == gid) & (odds.selection == "home")]
                if not o.empty:
                    won = int(g["home_score"] > g["away_score"])
                    rows.append({"prob": p_home, "won": won, "odds": float(o.iloc[0]["odds"])})

            hs, aws = int(g["home_score"]), int(g["away_score"])
            cum.setdefault(ht, []).append((hs, aws))
            cum.setdefault(at, []).append((aws, hs))

        if rows:
            df_pt = pd.DataFrame(rows)
            rep = build_ev_backtest_report(df_pt, prob_col="prob")
            gap = rep.avg_model_prob - rep.actual_win_rate
            bias = "高估" if gap > 0.03 else ("低估" if gap < -0.03 else "尚可")
            print(f"賽前 Log5 樣本 {rep.n_bets} 場（各隊至少 3 場歷史）")
            print(
                f"  模型={rep.avg_model_prob:.1%} 實際={rep.actual_win_rate:.1%} "
                f"差距={gap:+.1%} ({bias})"
            )
            print(
                f"  Brier={rep.brier_score:.4f} "
                f"正EV子集ROI={rep.roi_taken:+.2%} (n={rep.n_positive_ev})"
            )
        else:
            print("樣本不足")


if __name__ == "__main__":
    main()
