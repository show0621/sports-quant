"""模型方法論與貝氏管線 UI。"""
from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from sportsbet.models.bayesian_pipeline import METHODOLOGY_MARKDOWN, BayesianForecastPipeline


def _fmt_prob(v: float | None) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{float(v) * 100:.1f}%"


def render_methodology_overview() -> None:
    st.markdown(METHODOLOGY_MARKDOWN)
    st.markdown(
        """
```mermaid
flowchart TD
    A[①② 先驗: 賽季 + 畢氏] --> B[④ Log5 對戰]
    C[③ 近況勝率] --> D[⑤ Beta-Binomial 後驗]
    B --> E[⑥ 貝氏近況]
    D --> F[⑨ 集成後驗]
    E --> F
    G[⑦ 馬可夫 Hot/Cold] --> F
    H[⑧ H2H 前次交鋒] --> F
    F --> I[⑩ 傷兵似然修正]
    J[球員 box score λ] --> K[⑪ MC 8000 次]
    I --> K
    K --> L[⑫ 最終 PK 勝率]
```
        """
    )


def render_forecast_pipeline(fc: Any, *, expanded: bool = False) -> None:
    from sportsbet.models.bayesian_pipeline import build_pipeline_from_forecast

    pipeline: BayesianForecastPipeline = getattr(fc, "pipeline", None) or build_pipeline_from_forecast(fc)
    with st.expander("貝氏集成 PK 勝率管線", expanded=expanded):
        st.caption(pipeline.summary_markdown())
        show = pipeline.to_dataframe().copy()
        for col in ("主隊勝率", "客隊勝率"):
            if col in show.columns:
                show[col] = show[col].map(_fmt_prob)
        st.dataframe(show, use_container_width=True, hide_index=True)
