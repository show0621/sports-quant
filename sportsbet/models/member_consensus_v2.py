"""玩運彩 60%+ 會員共識 → 模型機率 V2 修正。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sportsbet import config
from sportsbet.models.calibration import calibrate_spread_prob, calibrate_win_prob
from sportsbet.models.totals import prob_home_covers_spread


@dataclass
class MemberConsensusSnapshot:
    ml_home_pct: float | None = None
    ml_away_pct: float | None = None
    spread_home_pct: float | None = None
    spread_away_pct: float | None = None
    over_pct: float | None = None
    under_pct: float | None = None
    sample_ml: int | None = None
    sample_spread: int | None = None
    sample_total: int | None = None

    @property
    def has_any(self) -> bool:
        return any(
            v is not None
            for v in (
                self.ml_home_pct,
                self.spread_home_pct,
                self.over_pct,
            )
        )


def snapshot_from_db_row(row: dict[str, Any] | None) -> MemberConsensusSnapshot | None:
    if not row:
        return None
    snap = MemberConsensusSnapshot(
        ml_home_pct=row.get("ml_home_pct"),
        ml_away_pct=row.get("ml_away_pct"),
        spread_home_pct=row.get("spread_home_pct"),
        spread_away_pct=row.get("spread_away_pct"),
        over_pct=row.get("over_pct"),
        under_pct=row.get("under_pct"),
        sample_ml=row.get("sample_ml"),
        sample_spread=row.get("sample_spread"),
        sample_total=row.get("sample_total"),
    )
    return snap if snap.has_any else None


def _blend(model_p: float | None, member_p: float | None, weight: float) -> float | None:
    if model_p is None:
        return None
    if member_p is None or weight <= 0:
        return model_p
    m = max(0.05, min(0.95, float(member_p)))
    p = max(0.05, min(0.95, float(model_p)))
    w = max(0.0, min(1.0, weight))
    return max(0.05, min(0.95, (1.0 - w) * p + w * m))


@dataclass
class ForecastV2Probs:
    home_win_prob_v2: float | None = None
    away_win_prob_v2: float | None = None
    prob_over_v2: float | None = None
    prob_under_v2: float | None = None
    prob_home_cover_v2: float | None = None
    prob_away_cover_v2: float | None = None
    member: MemberConsensusSnapshot | None = None


def compute_forecast_v2(
    *,
    sport: str,
    home_win_prob: float,
    prob_over: float | None,
    predicted_margin: float | None,
    spread_home_line: float | None,
    consensus: MemberConsensusSnapshot | None,
) -> ForecastV2Probs:
    """模型 V1 機率 + 玩運彩 60%+ 會員占比 → V2。"""
    if not config.MEMBER_CONSENSUS_ENABLED or consensus is None or not consensus.has_any:
        spread_home = None
        if predicted_margin is not None and spread_home_line is not None:
            spread_home = prob_home_covers_spread(float(spread_home_line), float(predicted_margin))
        return ForecastV2Probs(
            home_win_prob_v2=home_win_prob,
            away_win_prob_v2=1.0 - home_win_prob,
            prob_over_v2=prob_over,
            prob_under_v2=(1.0 - prob_over) if prob_over is not None else None,
            prob_home_cover_v2=spread_home,
            prob_away_cover_v2=(1.0 - spread_home) if spread_home is not None else None,
            member=consensus,
        )

    ml_home = _blend(
        home_win_prob,
        consensus.ml_home_pct,
        config.MEMBER_CONSENSUS_BLEND_ML,
    )
    if ml_home is not None:
        ml_home = calibrate_win_prob(ml_home, sport)  # type: ignore[arg-type]

    prob_o_v2 = prob_over
    if prob_over is not None and consensus.over_pct is not None:
        prob_o_v2 = _blend(prob_over, consensus.over_pct, config.MEMBER_CONSENSUS_BLEND_TOTAL)
        if prob_o_v2 is not None:
            prob_o_v2 = max(0.05, min(0.95, prob_o_v2))

    spread_home_model = None
    if predicted_margin is not None and spread_home_line is not None:
        spread_home_model = prob_home_covers_spread(float(spread_home_line), float(predicted_margin))

    spread_home_v2 = spread_home_model
    if spread_home_model is not None and consensus.spread_home_pct is not None:
        spread_home_v2 = _blend(
            spread_home_model,
            consensus.spread_home_pct,
            config.MEMBER_CONSENSUS_BLEND_SPREAD,
        )
        if spread_home_v2 is not None:
            spread_home_v2 = calibrate_spread_prob(spread_home_v2, sport)  # type: ignore[arg-type]

    home_v2 = ml_home if ml_home is not None else home_win_prob
    return ForecastV2Probs(
        home_win_prob_v2=home_v2,
        away_win_prob_v2=1.0 - home_v2,
        prob_over_v2=prob_o_v2,
        prob_under_v2=(1.0 - prob_o_v2) if prob_o_v2 is not None else None,
        prob_home_cover_v2=spread_home_v2,
        prob_away_cover_v2=(1.0 - spread_home_v2) if spread_home_v2 is not None else None,
        member=consensus,
    )
