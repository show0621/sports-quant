"""玩運彩 60%+ 會員共識 → V2 機率（獨立主線，不修改 V1 模型）。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sportsbet import config


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
                self.ml_away_pct,
                self.spread_home_pct,
                self.spread_away_pct,
                self.over_pct,
                self.under_pct,
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


def _clip_prob(p: float | None) -> float | None:
    if p is None:
        return None
    return max(0.05, min(0.95, float(p)))


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
    consensus: MemberConsensusSnapshot | None,
) -> ForecastV2Probs:
    """
    V2 = 玩運彩 60%+ 會員預測占比（純會員線，不與 V1 模型混合）。
    無會員資料時全部為 None。
    """
    if not config.MEMBER_CONSENSUS_ENABLED or consensus is None or not consensus.has_any:
        return ForecastV2Probs(member=consensus)

    ml_h = _clip_prob(consensus.ml_home_pct)
    ml_a = _clip_prob(consensus.ml_away_pct)
    if ml_h is not None and ml_a is not None:
        s = ml_h + ml_a
        if s > 0:
            ml_h, ml_a = ml_h / s, ml_a / s
    elif ml_h is not None:
        ml_a = 1.0 - ml_h
    elif ml_a is not None:
        ml_h = 1.0 - ml_a

    sp_h = _clip_prob(consensus.spread_home_pct)
    sp_a = _clip_prob(consensus.spread_away_pct)
    if sp_h is not None and sp_a is not None:
        s = sp_h + sp_a
        if s > 0:
            sp_h, sp_a = sp_h / s, sp_a / s

    ov = _clip_prob(consensus.over_pct)
    un = _clip_prob(consensus.under_pct)
    if ov is not None and un is not None:
        s = ov + un
        if s > 0:
            ov, un = ov / s, un / s
    elif ov is not None:
        un = 1.0 - ov
    elif un is not None:
        ov = 1.0 - un

    return ForecastV2Probs(
        home_win_prob_v2=ml_h,
        away_win_prob_v2=ml_a,
        prob_over_v2=ov,
        prob_under_v2=un,
        prob_home_cover_v2=sp_h,
        prob_away_cover_v2=sp_a,
        member=consensus,
    )
