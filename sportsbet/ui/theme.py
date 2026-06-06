"""看板主題與共用樣式。"""
from __future__ import annotations

import streamlit as st


def inject_dashboard_theme() -> None:
    st.markdown(
        """
        <style>
        :root {
            --sq-bg: #0b1220;
            --sq-card: #121c2e;
            --sq-accent: #3b82f6;
            --sq-accent2: #10b981;
            --sq-warn: #f59e0b;
            --sq-text: #e5e7eb;
            --sq-muted: #94a3b8;
        }
        .stApp {
            background: linear-gradient(165deg, #070b14 0%, #0f172a 45%, #111827 100%);
        }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%);
            border-right: 1px solid rgba(148,163,184,0.15);
        }
        .sq-hero {
            background: linear-gradient(135deg, rgba(59,130,246,0.18), rgba(16,185,129,0.12));
            border: 1px solid rgba(148,163,184,0.2);
            border-radius: 16px;
            padding: 1.1rem 1.4rem;
            margin-bottom: 1rem;
        }
        .sq-hero h1 {
            font-size: 1.55rem;
            margin: 0 0 0.35rem 0;
            color: #f8fafc;
            letter-spacing: 0.02em;
        }
        .sq-hero p {
            margin: 0;
            color: var(--sq-muted);
            font-size: 0.92rem;
        }
        .sq-live-card {
            background: var(--sq-card);
            border: 1px solid rgba(148,163,184,0.18);
            border-radius: 14px;
            padding: 0.85rem 1rem;
            margin-bottom: 0.65rem;
            box-shadow: 0 8px 24px rgba(0,0,0,0.25);
        }
        .sq-live-card.live {
            border-color: rgba(16,185,129,0.45);
            box-shadow: 0 0 0 1px rgba(16,185,129,0.15), 0 8px 24px rgba(0,0,0,0.25);
        }
        .sq-badge {
            display: inline-block;
            padding: 0.15rem 0.55rem;
            border-radius: 999px;
            font-size: 0.72rem;
            font-weight: 600;
            margin-right: 0.35rem;
            letter-spacing: 0.03em;
        }
        .sq-badge-post { background: rgba(245,158,11,0.2); color: #fcd34d; }
        .sq-badge-finals { background: rgba(239,68,68,0.22); color: #fca5a5; }
        .sq-badge-reg { background: rgba(59,130,246,0.18); color: #93c5fd; }
        .sq-badge-live { background: rgba(16,185,129,0.22); color: #6ee7b7; animation: sq-pulse 1.6s ease-in-out infinite; }
        .sq-score {
            font-size: 1.65rem;
            font-weight: 700;
            color: #f8fafc;
            letter-spacing: 0.04em;
        }
        .sq-team { font-size: 0.95rem; color: #e2e8f0; font-weight: 600; }
        .sq-clock { color: #94a3b8; font-size: 0.82rem; }
        .sq-team-inline {
            display: flex;
            align-items: center;
            gap: 0.55rem;
        }
        .sq-team-block .sq-team-inline {
            justify-content: flex-start;
        }
        div[style*="text-align:right"] .sq-team-inline {
            flex-direction: row-reverse;
        }
        div[style*="text-align:right"] .sq-team-text {
            text-align: right;
        }
        .sq-team-logo {
            border-radius: 6px;
            background: rgba(255,255,255,0.06);
            flex-shrink: 0;
        }
        .sq-team-en {
            font-size: 0.92rem;
            font-weight: 700;
            color: #f1f5f9;
            line-height: 1.25;
        }
        .sq-team-zh {
            font-size: 0.78rem;
            color: #94a3b8;
            margin-top: 0.1rem;
            line-height: 1.2;
        }
        .sq-odds-box {
            background: rgba(18,28,46,0.85);
            border: 1px solid rgba(148,163,184,0.15);
            border-radius: 12px;
            padding: 0.65rem 0.85rem;
            margin-bottom: 0.5rem;
        }
        @keyframes sq-pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.65; }
        }
        div[data-testid="stMetric"] {
            background: rgba(18,28,46,0.75);
            border: 1px solid rgba(148,163,184,0.12);
            border-radius: 12px;
            padding: 0.5rem 0.75rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
