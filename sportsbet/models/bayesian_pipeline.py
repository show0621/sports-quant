"""
貝氏集成預測管線：先驗 → 似然 → 後驗 → 傷兵/球員 → MC → 最終 PK 勝率。

各階段對應：
- 歷史勝率、畢氏勝率：先驗 π
- Log5 / Beta-Binomial / 馬可夫 / H2H：似然或共軛後驗更新
- 集成層：加權平均後驗（傷兵前）
- 傷兵、球員得失分：似然比修正
- Monte Carlo：得分過程後驗，與集成勝率混合
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd

from sportsbet import config

Sport = Literal["nba", "mlb"]


@dataclass
class PipelineStage:
    """單一步驟的主客勝率（或該步後之值）。"""

    key: str
    name_zh: str
    role: str
    home_prob: float | None
    away_prob: float | None
    note: str = ""


@dataclass
class BayesianForecastPipeline:
    """單場完整貝氏集成管線（供 UI / 覆盤）。"""

    sport: str
    home_team: str
    away_team: str
    match_date: str
    stages: list[PipelineStage] = field(default_factory=list)
    final_home: float = 0.5
    final_away: float = 0.5
    player_home_pts_est: float | None = None
    player_away_pts_est: float | None = None
    h2h_home_win_pct: float | None = None

    def to_dataframe(self) -> pd.DataFrame:
        rows = []
        for s in self.stages:
            rows.append(
                {
                    "步驟": s.name_zh,
                    "角色": s.role,
                    "主隊勝率": s.home_prob,
                    "客隊勝率": s.away_prob,
                    "說明": s.note,
                }
            )
        return pd.DataFrame(rows)

    def summary_markdown(self) -> str:
        lines = [
            "**貝氏集成流程**：先驗（賽季/畢氏）→ Log5/Beta/馬可夫/H2H 似然 → 集成後驗 → "
            "傷兵修正 → 球員得分 λ → MC 抽樣 → **最終 PK 勝率**",
        ]
        if self.h2h_home_win_pct is not None:
            lines.append(f"- 前次交鋒主場勝率：{self.h2h_home_win_pct:.1%}")
        if self.player_home_pts_est is not None and self.player_away_pts_est is not None:
            lines.append(
                f"- 球員近況估分（主/客）：{self.player_home_pts_est:.1f} / {self.player_away_pts_est:.1f}"
            )
        return "\n".join(lines)


def _pct(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v * 100:.1f}%"


def _rebuild_prob_breakdown(fc: Any) -> Any | None:
    """DB 還原的 forecast 若缺 prob_breakdown，用已存 stats 重算 Markov/Beta/H2H。"""
    pb = getattr(fc, "prob_breakdown", None)
    if pb is not None:
        return pb
    home = fc.home
    away = fc.away
    if not home.rs_per_game or not away.rs_per_game:
        return None
    try:
        from sportsbet.data.database import SportsDatabase
        from sportsbet.models.analytics_engine import AnalyticsEngine
        from sportsbet.models.probability_engine import ensemble_matchup_probability

        db = SportsDatabase()
        eng = AnalyticsEngine(fc.sport)
        return ensemble_matchup_probability(
            eng,
            fc.sport,
            fc.home_team,
            fc.away_team,
            home.rs_per_game,
            home.ra_per_game,
            away.rs_per_game,
            away.ra_per_game,
            fc.match_date,
            home_games=int(home.games or 0),
            away_games=int(away.games or 0),
            home_season_win_pct=home.season_win_pct,
            away_season_win_pct=away.season_win_pct,
            home_recent_win_pct=home.recent_win_pct,
            away_recent_win_pct=away.recent_win_pct,
            db=db,
        )
    except Exception:
        return None


def ensure_forecast_pipeline(fc: Any) -> BayesianForecastPipeline:
    """取得或組裝完整管線（供 UI 評分明細）。"""
    pipeline = getattr(fc, "pipeline", None)
    if pipeline is not None and pipeline.stages:
        return pipeline
    pipeline = build_pipeline_from_forecast(fc)
    fc.pipeline = pipeline
    return pipeline


def build_pipeline_from_forecast(fc: Any) -> BayesianForecastPipeline:
    """由 GameForecast 組裝完整管線分解。"""
    from sportsbet.models.player_scoring import (
        _team_lineup_expected_points,
        player_matchup_win_prob,
    )

    home = fc.home
    away = fc.away
    pb = _rebuild_prob_breakdown(fc)
    sim = getattr(fc, "sim_result", None)

    h2h_pct = None
    if pb and getattr(pb, "context", None):
        h2h_pct = getattr(pb.context, "h2h_home_win_pct", None)

    stages: list[PipelineStage] = [
        PipelineStage(
            "season", "① 賽季勝率（歷史 W-L）", "先驗 π",
            home.season_win_pct, away.season_win_pct,
            "長期實際勝率",
        ),
        PipelineStage(
            "pyth", "② 畢氏勝率（得失分）", "先驗 π",
            home.pythagorean_win_pct, away.pythagorean_win_pct,
            "Pythagorean expectation",
        ),
        PipelineStage(
            "recent", "③ 近況勝率", "似然（近期樣本）",
            home.recent_win_pct, away.recent_win_pct,
            f"近 {config.BAYES_RECENT_GAMES} 場",
        ),
        PipelineStage(
            "log5", "④ Log5 對戰先驗", "先驗（對戰調整）",
            home.log5_matchup_win_pct, away.log5_matchup_win_pct,
            "兩隊實力 + 主場優勢",
        ),
    ]

    if pb is not None:
        stages.extend(
            [
                PipelineStage(
                    "beta", "⑤ Beta-Binomial 後驗", "共軛後驗",
                    pb.beta_home, pb.beta_away,
                    "畢氏先驗 + 近況勝場數",
                ),
                PipelineStage(
                    "bayes_recent", "⑥ 貝氏近況修正", "後驗",
                    pb.bayesian_home, pb.bayesian_away,
                    "Log5 後驗 + 近況權重",
                ),
                PipelineStage(
                    "markov", "⑦ 馬可夫鏈（Hot/Cold）", "轉移後驗",
                    pb.markov_home, pb.markov_away,
                    "連勝/連敗狀態",
                ),
            ]
        )
        if h2h_pct is not None:
            stages.append(
                PipelineStage(
                    "h2h", "⑧ 前次交鋒 H2H", "似然比",
                    h2h_pct, 1.0 - h2h_pct,
                    f"似然比 LR 主 {pb.context_lr_home:.3f} / 客 {pb.context_lr_away:.3f}"
                    if pb.context else "",
                )
            )
        stages.append(
            PipelineStage(
                "ensemble", "⑨ 集成後驗（傷兵前）", "後驗",
                pb.final_home, pb.final_away,
                "Log5+Beta+Bayes+Markov+H2H 加權",
            )
        )
    else:
        stages.append(
            PipelineStage(
                "ensemble", "⑨ 集成後驗（傷兵前）", "後驗",
                fc.home_win_prob_base, fc.away_win_prob_base,
                "Log5 + 貝氏近況",
            )
        )

    base_h = fc.home_win_prob_base if fc.home_win_prob_base is not None else fc.home_win_prob
    base_a = fc.away_win_prob_base if fc.away_win_prob_base is not None else fc.away_win_prob
    inj_h = (base_h + fc.home_injury_adj) if fc.home_injury_adj is not None else None
    inj_a = (base_a + fc.away_injury_adj) if fc.away_injury_adj is not None else None
    inj_note = ""
    if fc.home_injury_adj is not None or fc.away_injury_adj is not None:
        inj_note = (
            f"主 { _pct(base_h) }→{ _pct(inj_h) } ({(fc.home_injury_adj or 0):+.1%}) · "
            f"客 { _pct(base_a) }→{ _pct(inj_a) } ({(fc.away_injury_adj or 0):+.1%})"
        )
    stages.append(
        PipelineStage(
            "injury", "⑩ 傷兵 / 陣容調整", "似然修正",
            inj_h, inj_a, inj_note or "無傷兵/球員資料 · 不輸出虛構修正",
        )
    )

    ph = pa = None
    if fc.game_id and fc.sport == "nba":
        try:
            from sportsbet.data.database import SportsDatabase

            db = SportsDatabase()
            ph = _team_lineup_expected_points(db, "nba", fc.home_team, fc.match_date)
            pa = _team_lineup_expected_points(db, "nba", fc.away_team, fc.match_date)
        except Exception:
            pass

    player_pk = player_matchup_win_prob(ph, pa)
    player_note = ""
    if ph is not None and pa is not None:
        player_note = f"近況估分 主 {ph:.0f} · 客 {pa:.0f}"
    stages.append(
        PipelineStage(
            "player_pk", "⑩b 球員數據 PK", "box score λ",
            player_pk[0] if player_pk else None,
            player_pk[1] if player_pk else None,
            player_note or "無 box score / 陣容連結 · 不輸出虛構值",
        )
    )

    if sim is not None:
        stages.append(
            PipelineStage(
                "mc", "⑪ Monte Carlo 後驗", "抽樣後驗",
                sim.home_win_prob, 1.0 - sim.home_win_prob,
                f"{sim.n_sims} 次 · 中位比分 {sim.median_away_score:.0f}–{sim.median_home_score:.0f}",
            )
        )

    stages.append(
        PipelineStage(
            "final", "⑫ 最終 PK 修正勝率", "決策後驗",
            fc.home_win_prob, fc.away_win_prob,
            "Log5+Bayes+Markov+H2H → 傷兵 → 球員λ → MC 混合",
        )
    )

    return BayesianForecastPipeline(
        sport=fc.sport,
        home_team=fc.home_team,
        away_team=fc.away_team,
        match_date=fc.match_date,
        stages=stages,
        final_home=fc.home_win_prob,
        final_away=fc.away_win_prob,
        player_home_pts_est=ph,
        player_away_pts_est=pa,
        h2h_home_win_pct=h2h_pct,
    )


METHODOLOGY_MARKDOWN = """
### 貝氏集成 PK 勝率模型

模型將多源訊息視為 **先驗 π** 與 **似然 L(data|θ)**，逐步更新為 **後驗 P(主勝|資料)**：

| 階段 | 類型 | 資料來源 |
|------|------|----------|
| ① 賽季勝率 | 先驗 | 歷史 W-L |
| ② 畢氏勝率 | 先驗 | 得失分期望 |
| ③ 近況勝率 | 似然 | 近 N 場結果 |
| ④ Log5 | 先驗 | 兩隊對戰調整 |
| ⑤ Beta-Binomial | 共軛後驗 | 近況勝場 + 畢氏先驗 |
| ⑥ 貝氏近況 | 後驗 | Log5 融合近況 |
| ⑦ 馬可夫鏈 | 轉移後驗 | Hot/Cold 狀態 |
| ⑧ H2H | 似然比 | 前次交鋒 / 系列賽 |
| ⑨ 集成 | 後驗 | 加權融合 ⑤–⑧ |
| ⑩ 傷兵 | 似然修正 | 缺陣 VORP/WAR |
| ⑩b 球員 box | λ 調整 | 近況 PTS/失分 → Poisson λ |
| ⑪ MC | 抽樣後驗 | Poisson 得分 8000 次 |
| ⑫ 最終 | 決策 | 65% 集成 + 35% MC（勝率） |

**大小分 / 讓分**：由校準後 λ 與 MC 總分/分差分布計算 P(Over)、P(Cover)。
"""
