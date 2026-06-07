"""看板主題：輕白、玩運彩 / Bing Sports 風格，韻彩分析師版面。"""
from __future__ import annotations

import streamlit as st


def inject_dashboard_theme() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;600;700&family=Noto+Serif+TC:wght@500;600&display=swap');

        :root {
            --sq-bg: #f4f6f9;
            --sq-surface: #ffffff;
            --sq-border: #e2e8f0;
            --sq-border-light: #eef2f6;
            --sq-ink: #1e293b;
            --sq-muted: #64748b;
            --sq-brand: #007a54;
            --sq-brand-soft: #e8f5ef;
            --sq-accent: #2563eb;
            --sq-live: #dc2626;
            --sq-warn: #d97706;
            --sq-shadow: 0 1px 3px rgba(15,23,42,0.06), 0 4px 14px rgba(15,23,42,0.04);
        }

        .stApp {
            background: var(--sq-bg);
            font-family: "Noto Sans TC", "Segoe UI", sans-serif;
            color: var(--sq-ink);
        }
        [data-testid="stSidebar"] {
            background: var(--sq-surface);
            border-right: 1px solid var(--sq-border);
        }
        [data-testid="stSidebar"] .stMarkdown { color: var(--sq-ink); }

        /* 頂部品牌 */
        .sq-masthead {
            background: linear-gradient(135deg, #ffffff 0%, #f0faf5 55%, #f8fbff 100%);
            border: 1px solid var(--sq-border);
            border-radius: 16px;
            padding: 1.25rem 1.5rem 1.1rem;
            margin-bottom: 1rem;
            box-shadow: var(--sq-shadow);
        }
        .sq-masthead-brand {
            font-family: "Noto Serif TC", "Noto Sans TC", serif;
            font-size: 1.45rem;
            font-weight: 600;
            color: var(--sq-ink);
            letter-spacing: 0.06em;
        }
        .sq-masthead-brand span { color: var(--sq-brand); }
        .sq-quarter-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.88rem;
            margin: 0.5rem 0 1rem;
        }
        .sq-quarter-table th, .sq-quarter-table td {
            border: 1px solid var(--sq-border);
            padding: 0.35rem 0.5rem;
            text-align: center;
        }
        .sq-quarter-table th:first-child, .sq-quarter-table td:first-child {
            text-align: left;
        }
        .sq-game-center-header {
            background: var(--sq-surface);
            border: 1px solid var(--sq-border);
            border-radius: 12px;
            padding: 1rem 1.2rem;
            margin-bottom: 1rem;
            box-shadow: var(--sq-shadow);
        }
        .sq-gc-score { font-size: 2rem; font-weight: 700; text-align: center; }
        .sq-gc-matchup { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
        .sq-gc-meta { color: var(--sq-muted); font-size: 0.85rem; margin-bottom: 0.5rem; }
        .sq-masthead-sub {
            margin-top: 0.35rem;
            color: var(--sq-muted);
            font-size: 0.88rem;
            letter-spacing: 0.02em;
            line-height: 1.5;
        }

        /* 區塊標題 */
        .sq-hero {
            background: var(--sq-surface);
            border: 1px solid var(--sq-border);
            border-left: 4px solid var(--sq-brand);
            border-radius: 12px;
            padding: 1rem 1.25rem;
            margin-bottom: 0.85rem;
            box-shadow: var(--sq-shadow);
        }
        .sq-hero h1 {
            font-family: "Noto Serif TC", serif;
            font-size: 1.25rem;
            font-weight: 600;
            margin: 0 0 0.3rem 0;
            color: var(--sq-ink);
            letter-spacing: 0.03em;
        }
        .sq-hero p {
            margin: 0;
            color: var(--sq-muted);
            font-size: 0.85rem;
        }

        /* 賽事卡片 */
        .sq-live-card {
            background: var(--sq-surface);
            border: 1px solid var(--sq-border);
            border-radius: 14px;
            padding: 1rem 1.15rem;
            margin-bottom: 0.75rem;
            box-shadow: var(--sq-shadow);
            transition: box-shadow 0.15s ease;
        }
        .sq-live-card:hover {
            box-shadow: 0 2px 8px rgba(15,23,42,0.08), 0 8px 24px rgba(15,23,42,0.06);
        }
        .sq-live-card.live {
            border-color: #fecaca;
            background: linear-gradient(180deg, #fffafa 0%, #ffffff 100%);
            box-shadow: 0 0 0 1px rgba(220,38,38,0.12), var(--sq-shadow);
        }

        /* 標籤 */
        .sq-badge {
            display: inline-block;
            padding: 0.12rem 0.5rem;
            border-radius: 999px;
            font-size: 0.68rem;
            font-weight: 600;
            margin: 0 0.2rem 0.25rem 0;
            letter-spacing: 0.04em;
        }
        .sq-badge-live {
            background: #fee2e2;
            color: #b91c1c;
            animation: sq-pulse 1.8s ease-in-out infinite;
        }
        .sq-badge-post { background: #fef3c7; color: #b45309; }
        .sq-badge-finals { background: #fce7f3; color: #be185d; }
        .sq-badge-reg { background: #dbeafe; color: #1d4ed8; }

        .sq-score {
            font-size: 1.75rem;
            font-weight: 700;
            color: var(--sq-ink);
            letter-spacing: 0.06em;
            line-height: 1.2;
        }
        .sq-clock { color: var(--sq-muted); font-size: 0.8rem; margin-top: 0.15rem; }

        /* 隊名 */
        .sq-team-inline {
            display: flex;
            align-items: center;
            gap: 0.55rem;
        }
        .sq-team-block .sq-team-inline { justify-content: flex-start; }
        div[style*="text-align:right"] .sq-team-inline { flex-direction: row-reverse; }
        div[style*="text-align:right"] .sq-team-text { text-align: right; }
        .sq-team-logo {
            border-radius: 8px;
            background: #f8fafc;
            border: 1px solid var(--sq-border-light);
            flex-shrink: 0;
        }
        .sq-team-en {
            font-size: 0.9rem;
            font-weight: 700;
            color: var(--sq-ink);
            line-height: 1.25;
        }
        .sq-team-zh {
            font-size: 0.76rem;
            color: var(--sq-muted);
            margin-top: 0.08rem;
        }

        /* 即時賽況 · 模型預測列 */
        .sq-pred-strip {
            margin-top: 0.75rem;
            padding-top: 0.75rem;
            border-top: 1px dashed var(--sq-border);
        }
        .sq-pred-strip.sq-pred-empty {
            font-size: 0.82rem;
            color: var(--sq-muted);
            padding: 0.5rem 0 0.15rem;
        }
        .sq-pred-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 0.55rem;
        }
        @media (max-width: 1100px) {
            .sq-pred-grid { grid-template-columns: repeat(2, 1fr); }
        }
        @media (max-width: 768px) {
            .sq-pred-grid { grid-template-columns: 1fr; }
        }
        .sq-pred-cell {
            background: #f8fafc;
            border: 1px solid var(--sq-border-light);
            border-radius: 10px;
            padding: 0.55rem 0.7rem;
        }
        .sq-pred-label {
            font-size: 0.72rem;
            font-weight: 700;
            color: var(--sq-brand);
            letter-spacing: 0.06em;
            margin-bottom: 0.2rem;
        }
        .sq-pred-value {
            font-size: 0.88rem;
            font-weight: 600;
            color: var(--sq-ink);
            line-height: 1.35;
        }
        .sq-pred-sub {
            font-size: 0.74rem;
            color: var(--sq-muted);
            margin-top: 0.15rem;
        }
        .sq-pred-hit {
            display: inline-block;
            margin-top: 0.45rem;
            font-size: 0.78rem;
            font-weight: 600;
            padding: 0.12rem 0.5rem;
            border-radius: 999px;
        }
        .sq-pred-ok { background: #dcfce7; color: #166534; }
        .sq-pred-miss { background: #fee2e2; color: #991b1b; }
        .sq-pred-ev-pos { color: #15803d; font-weight: 600; }
        .sq-pred-ev-neg { color: #94a3b8; }
        .sq-pred-result { margin-top: 0.25rem; }
        .sq-pred-summary {
            display: flex;
            flex-wrap: wrap;
            gap: 0.35rem;
            margin-top: 0.5rem;
            padding-top: 0.45rem;
            border-top: 1px dashed var(--sq-border-light);
        }

        /* 球隊評分明細 */
        .sq-rating-panel {
            margin-top: 0.65rem;
            padding-top: 0.65rem;
            border-top: 1px dashed var(--sq-border-light);
        }
        .sq-rating-title {
            font-size: 0.78rem;
            font-weight: 600;
            color: var(--sq-muted);
            letter-spacing: 0.06em;
            margin-bottom: 0.45rem;
        }
        .sq-rating-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.82rem;
        }
        .sq-rating-table th {
            text-align: center;
            padding: 0.35rem 0.5rem;
            font-weight: 600;
            color: var(--sq-text);
            border-bottom: 1px solid var(--sq-border);
        }
        .sq-rating-table th:first-child { text-align: left; width: 28%; }
        .sq-rating-zh { font-size: 0.72rem; color: var(--sq-muted); font-weight: 400; }
        .sq-rating-metric {
            padding: 0.3rem 0.5rem;
            color: var(--sq-muted);
            font-weight: 500;
        }
        .sq-rating-val {
            text-align: center;
            padding: 0.3rem 0.5rem;
            font-variant-numeric: tabular-nums;
        }
        .sq-rating-val.away { background: #f8fafc; }
        .sq-rating-val.home { background: #f1f5f9; }
        .sq-rating-table tbody tr:nth-child(even) .sq-rating-val.away { background: #f1f5f9; }
        .sq-rating-table tbody tr:nth-child(even) .sq-rating-val.home { background: #e2e8f0; }
        .sq-rating-table tbody tr:last-child .sq-rating-val {
            font-weight: 700;
            color: var(--sq-primary);
        }
        .sq-rating-table tbody tr.sq-rating-final .sq-rating-val {
            font-weight: 700;
            color: var(--sq-primary);
            border-top: 2px solid var(--sq-border);
        }

        /* 盤口面板 */
        .sq-odds-panel {
            background: #f8fafc;
            border: 1px solid var(--sq-border);
            border-radius: 12px;
            padding: 0.85rem 1rem;
            margin: 0.5rem 0 0.75rem;
        }
        .sq-odds-panel h4 {
            margin: 0 0 0.65rem 0;
            font-size: 0.82rem;
            font-weight: 600;
            color: var(--sq-muted);
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }
        .sq-odds-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 0.65rem;
        }
        .sq-odds-grid.sq-odds-grid-4 {
            grid-template-columns: repeat(4, 1fr);
        }
        @media (max-width: 1100px) {
            .sq-odds-grid.sq-odds-grid-4 { grid-template-columns: repeat(2, 1fr); }
        }
        @media (max-width: 768px) {
            .sq-odds-grid { grid-template-columns: 1fr; }
            .sq-odds-grid.sq-odds-grid-4 { grid-template-columns: 1fr; }
        }
        .sq-rec-panel {
            margin-top: 0.75rem;
            padding: 0.65rem 0.75rem;
            background: var(--sq-surface);
            border: 1px solid var(--sq-border-light);
            border-radius: 10px;
        }
        .sq-rec-panel h4 {
            margin: 0 0 0.5rem 0;
            font-size: 0.82rem;
            font-weight: 600;
            color: var(--sq-muted);
        }
        .sq-odds-col {
            background: var(--sq-surface);
            border: 1px solid var(--sq-border-light);
            border-radius: 10px;
            padding: 0.65rem 0.75rem;
        }
        .sq-odds-col-title {
            font-size: 0.78rem;
            font-weight: 700;
            color: var(--sq-brand);
            margin-bottom: 0.35rem;
        }
        .sq-odds-line { font-size: 0.88rem; color: var(--sq-ink); line-height: 1.55; }
        .sq-odds-cap { font-size: 0.75rem; color: var(--sq-muted); margin-top: 0.25rem; }

        /* 傷兵跑馬燈 */
        .sq-injury-ticker {
            background: #fffbeb;
            color: #92400e;
            padding: 0.55rem 0.9rem;
            border-radius: 10px;
            border: 1px solid #fde68a;
            border-left: 4px solid var(--sq-warn);
            font-size: 0.84rem;
            margin-bottom: 0.85rem;
            overflow-x: auto;
            white-space: nowrap;
        }

        /* 分頁 */
        .stTabs [data-baseweb="tab-list"] {
            gap: 0.35rem;
            background: transparent;
            border-bottom: 1px solid var(--sq-border);
            padding-bottom: 0.25rem;
        }
        .stTabs [data-baseweb="tab"] {
            background: transparent;
            border-radius: 8px 8px 0 0;
            color: var(--sq-muted);
            font-weight: 500;
            padding: 0.45rem 0.85rem;
        }
        .stTabs [aria-selected="true"] {
            background: var(--sq-surface) !important;
            color: var(--sq-brand) !important;
            border: 1px solid var(--sq-border);
            border-bottom-color: var(--sq-surface) !important;
            font-weight: 600;
        }

        /* 指標卡 */
        div[data-testid="stMetric"] {
            background: var(--sq-surface);
            border: 1px solid var(--sq-border);
            border-radius: 12px;
            padding: 0.55rem 0.8rem;
            box-shadow: var(--sq-shadow);
        }
        div[data-testid="stMetric"] label {
            color: var(--sq-muted) !important;
            font-size: 0.78rem !important;
        }
        div[data-testid="stMetric"] [data-testid="stMetricValue"] {
            color: var(--sq-ink) !important;
        }

        h1, h2, h3 { color: var(--sq-ink) !important; font-weight: 600 !important; }
        .stCaption { color: var(--sq-muted) !important; }

        @keyframes sq-pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.72; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_masthead(sport: str) -> None:
    """韻彩分析師品牌列。"""
    label = "NBA 籃球" if sport == "nba" else "MLB 棒球"
    st.markdown(
        f"""
        <div class="sq-masthead">
            <div class="sq-masthead-brand"><span>韻彩</span> · 賽事量化分析</div>
            <div class="sq-masthead-sub">
                {label} · 即時賽況 · 台灣運彩盤口 · 模型勝率與大小分推演
                · 以數據閱讀比賽，從容下注
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
