"""Design tokens, global CSS and the Plotly chart template."""
from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

INK = "#08111F"
PANEL = "#0F1B2E"
PANEL_2 = "#13223A"
RULE = "#1D2C45"
TEXT = "#E3E9F2"
MUTED = "#8B9AB2"
TEAL = "#2BB3A3"
CYAN = "#45C4E0"
AMBER = "#E9A23B"
RED = "#E5534B"
SLATE = "#6C7FA0"

SAND = "#CDBB7A"
# An ordered ramp (cool and dim to hot and bright) so a higher band always looks more urgent.
SEVERITY_COLORS = {"Critical": RED, "High": AMBER, "Moderate": SAND, "Low": SLATE, "Unscored": SLATE}
NO_ALERT = "#18283F"
RELEVANCE_COLORS = {"direct": TEAL, "indirect": CYAN, "uncertain": MUTED, "unrelated": SLATE}
FONT = "IBM Plex Sans, Segoe UI, sans-serif"

CSS = f"""
<style>
:root {{
  --ink:{INK}; --panel:{PANEL}; --panel2:{PANEL_2}; --rule:{RULE}; --text:{TEXT}; --muted:{MUTED};
  --teal:{TEAL}; --cyan:{CYAN}; --amber:{AMBER}; --red:{RED}; --slate:{SLATE};
}}
html, body, [data-testid="stAppViewContainer"] {{ font-variant-numeric: tabular-nums; }}
[data-testid="stMainBlockContainer"] {{ padding-top: 1.6rem; padding-bottom: 3rem; max-width: 1500px; }}
[data-testid="stSidebar"] {{ border-right: 1px solid var(--rule); }}
h1, h2, h3 {{ letter-spacing: -0.01em; }}
a {{ text-decoration: none; }}
a:focus-visible, button:focus-visible {{ outline: 2px solid var(--cyan); outline-offset: 2px; }}

.ms-brand {{ display:flex; gap:.6rem; align-items:center; margin:.2rem 0 .4rem 0; }}
.ms-brand svg {{ flex: 0 0 auto; }}
.ms-brand-name {{ font-weight:600; font-size:1.08rem; color:var(--text); line-height:1.1; }}
.ms-brand-sub {{ font-size:.78rem; color:var(--muted); line-height:1.25; }}

.ms-head {{ display:flex; justify-content:space-between; align-items:flex-end; gap:1rem; flex-wrap:wrap;
            border-bottom:1px solid var(--rule); padding-bottom:.7rem; margin-bottom:1.1rem; }}
.ms-head h1 {{ font-size:1.55rem; margin:0; padding:0; font-weight:600; }}
.ms-head p {{ margin:.25rem 0 0 0; color:var(--muted); font-size:.92rem; max-width:72ch; }}
.ms-pills {{ display:flex; gap:.4rem; flex-wrap:wrap; justify-content:flex-end; }}
.ms-pills.left {{ justify-content:flex-start; margin:.1rem 0 .6rem; }}
.ms-pill {{ font-size:.76rem; padding:.18rem .55rem; border-radius:999px; border:1px solid var(--rule);
            color:var(--muted); background:var(--panel); white-space:nowrap; }}
.ms-pill b {{ color:var(--text); font-weight:500; }}
.ms-pill.live {{ border-color:rgba(43,179,163,.55); color:var(--teal); }}
.ms-pill.live b {{ color:var(--teal); }}
.ms-pill.warn {{ border-color:rgba(233,162,59,.6); color:var(--amber); }}
.ms-pill.warn b {{ color:var(--amber); }}
.ms-pill.bad {{ border-color:rgba(229,83,75,.6); color:var(--red); }}

.ms-banner {{ border:1px solid rgba(233,162,59,.55); background:rgba(233,162,59,.08); color:#F3C27A;
              border-radius:6px; padding:.55rem .8rem; font-size:.88rem; margin-bottom:1rem; }}
.ms-banner.bad {{ border-color:rgba(229,83,75,.55); background:rgba(229,83,75,.08); color:#F2A19B; }}
.ms-banner.info {{ border-color:rgba(69,196,224,.45); background:rgba(69,196,224,.07); color:#A9E3F0; }}

.ms-kpis {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); border:1px solid var(--rule);
            border-radius:6px; background:var(--panel); margin-bottom:1.1rem; }}
.ms-kpi {{ padding:.75rem .95rem; border-right:1px solid var(--rule); min-width:0; }}
.ms-kpi:last-child {{ border-right:none; }}
.ms-kpi .l {{ font-size:.78rem; color:var(--muted); }}
.ms-kpi .v {{ font-size:1.45rem; font-weight:600; color:var(--text); margin-top:.15rem; line-height:1.15; }}
.ms-kpi .s {{ font-size:.78rem; color:var(--muted); margin-top:.15rem; }}
.ms-kpi .pos {{ color:var(--teal); }} .ms-kpi .neg {{ color:var(--red); }}

.ms-sev {{ display:inline-block; font-size:.74rem; font-weight:600; padding:.08rem .5rem; border-radius:4px;
           border:1px solid currentColor; }}

.ms-section {{ font-size:1.02rem; font-weight:600; margin:1.3rem 0 .5rem 0; color:var(--text); }}
.ms-note {{ font-size:.82rem; color:var(--muted); margin:.2rem 0 .6rem 0; }}

.ms-stages {{ list-style:none; margin:0; padding:0; }}
.ms-stages li {{ display:flex; gap:.6rem; align-items:flex-start; padding:.45rem 0; border-bottom:1px solid var(--rule); }}
.ms-stages li:last-child {{ border-bottom:none; }}
.ms-dot {{ width:.72rem; height:.72rem; border-radius:50%; margin-top:.3rem; flex:0 0 auto;
           border:2px solid var(--slate); }}
.ms-dot.done {{ background:var(--teal); border-color:var(--teal); }}
.ms-dot.running {{ border-color:var(--cyan); background:transparent; }}
.ms-dot.warning {{ background:var(--amber); border-color:var(--amber); }}
.ms-dot.error {{ background:var(--red); border-color:var(--red); }}
.ms-stage-name {{ font-size:.9rem; color:var(--text); }}
.ms-stage-sub {{ font-size:.76rem; color:var(--muted); }}

.ms-box {{ border:1px solid var(--rule); border-left-width:3px; border-radius:6px; padding:.65rem .85rem;
           background:var(--panel); margin-bottom:.7rem; }}
.ms-box.observed {{ border-left-color:var(--teal); }}
.ms-box.assumed {{ border-left-color:var(--amber); }}
.ms-box.result {{ border-left-color:var(--cyan); }}
.ms-box .t {{ font-size:.78rem; color:var(--muted); margin-bottom:.25rem; }}
.ms-box .b {{ font-size:.95rem; color:var(--text); }}
.ms-formula {{ font-size:.82rem; color:var(--muted); }}

.ms-verdict {{ border:1px solid var(--rule); border-radius:6px; padding:.9rem 1rem; background:var(--panel2); }}
.ms-verdict .k {{ font-size:.8rem; color:var(--muted); }}
.ms-verdict .h {{ font-size:1.18rem; font-weight:600; margin:.15rem 0 .35rem 0; }}
.ms-verdict .c {{ font-size:.9rem; color:#C9D3E2; }}
.ms-log {{ font-size:.82rem; line-height:1.45; }}
.ms-log .ok {{ color:var(--teal); }} .ms-log .err {{ color:var(--red); }} .ms-log .warn {{ color:var(--amber); }}
.ms-log .who {{ color:var(--muted); }}
.ms-alert {{ border:1px solid var(--rule); border-left:3px solid var(--cyan); border-radius:6px;
             background:var(--panel); padding:.8rem 1rem; margin:.4rem 0 .8rem 0; }}
.ms-alert .title {{ font-size:1.12rem; font-weight:600; color:var(--text); }}
.ms-alert .meta {{ font-size:.86rem; color:var(--muted); margin:.15rem 0 .55rem 0; }}
.ms-alert .grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(160px, 1fr)); gap:.5rem 1rem;
                   margin-bottom:.55rem; }}
.ms-alert .grid .l {{ font-size:.76rem; color:var(--muted); }}
.ms-alert .grid .v {{ font-size:.98rem; color:var(--text); }}
.ms-alert .why {{ font-size:.92rem; color:#C9D3E2; line-height:1.45; }}
.ms-empty {{ border:1px dashed var(--rule); border-radius:6px; padding:1rem 1.1rem; background:var(--panel);
             color:var(--text); margin:.6rem 0; }}
.ms-empty .h {{ font-weight:600; margin-bottom:.25rem; }}
.ms-empty .b {{ font-size:.9rem; color:var(--muted); }}
.ms-q {{ font-size:.8rem; letter-spacing:.02em; color:var(--muted); text-transform:uppercase; margin:1.1rem 0 .3rem 0; }}
.ms-answer {{ font-size:1rem; line-height:1.55; color:var(--text); }}
.ms-status {{ display:inline-block; font-size:.74rem; font-weight:600; padding:.08rem .5rem; border-radius:4px;
              border:1px solid currentColor; margin-right:.4rem; }}
.ms-status.verified {{ color:var(--teal); }} .ms-status.provisional {{ color:var(--amber); }}
.ms-status.unresolved {{ color:#B9C6D8; }}
.ms-catalyst {{ border:1px solid var(--rule); border-left:3px solid var(--amber); border-radius:6px;
                background:var(--panel); padding:.7rem .9rem; margin:.6rem 0; }}
.ms-catalyst.A {{ border-left-color:var(--teal); }} .ms-catalyst.C {{ border-left-color:var(--slate); }}
.ms-catalyst .lvl {{ font-size:.78rem; color:var(--muted); }}
.ms-catalyst .hl {{ font-size:.98rem; color:var(--text); margin:.2rem 0; }}
.ms-catalyst .src {{ font-size:.82rem; color:var(--muted); }}
.ms-action {{ border:1px solid rgba(69,196,224,.5); border-radius:6px; background:rgba(69,196,224,.06);
              padding:.8rem 1rem; margin:.4rem 0 .6rem 0; }}
.ms-action .p {{ font-size:1.05rem; font-weight:600; color:var(--text); }}
.ms-action .w {{ font-size:.9rem; color:#C9D3E2; margin:.3rem 0 .5rem 0; }}
.ms-action ol {{ margin:.2rem 0 .5rem 1.2rem; padding:0; font-size:.92rem; color:var(--text); }}
.ms-action .k {{ font-size:.8rem; color:var(--muted); margin-top:.35rem; }}
.ms-action .v {{ font-size:.9rem; color:var(--text); }}
.ms-reading {{ border:1px solid rgba(43,179,163,.55); border-left:4px solid rgba(43,179,163,.9); border-radius:6px;
               background:rgba(43,179,163,.06); padding:.75rem 1rem; margin:.5rem 0 .4rem 0; }}
.ms-reading.muted {{ border-color:rgba(150,160,175,.35); border-left-color:rgba(150,160,175,.6);
                     background:rgba(150,160,175,.05); padding:.5rem .9rem; }}
.ms-reading .h {{ font-size:1rem; font-weight:600; color:var(--text); }}
.ms-reading .sub {{ font-size:.82rem; color:var(--muted); margin:.15rem 0 .35rem 0; }}
.ms-reading .k {{ font-size:.8rem; color:var(--muted); margin-top:.45rem; }}
.ms-reading .v {{ font-size:.92rem; color:var(--text); }}
.ms-reading ul, .ms-reading ol {{ margin:.2rem 0 .3rem 1.2rem; padding:0; font-size:.92rem; color:var(--text); }}
.ms-reading li {{ margin:.15rem 0; }}
.ms-reading .foot {{ font-size:.8rem; color:var(--muted); margin-top:.55rem; border-top:1px solid rgba(150,160,175,.25);
                     padding-top:.4rem; }}
@media (prefers-reduced-motion: reduce) {{ * {{ transition:none !important; animation:none !important; }} }}
</style>
"""

BRAND_SVG = f"""<svg width="30" height="30" viewBox="0 0 30 30" aria-hidden="true">
<circle cx="15" cy="15" r="13" fill="none" stroke="{RULE}" stroke-width="2"/>
<circle cx="15" cy="15" r="8" fill="none" stroke="{RULE}" stroke-width="2"/>
<path d="M15 15 L15 2 A13 13 0 0 1 27.4 11.2 Z" fill="{TEAL}" opacity=".85"/>
<circle cx="21.5" cy="9.5" r="2.2" fill="{AMBER}"/>
</svg>"""


def inject_css() -> None:
    st.html(CSS)


def register_plotly_template() -> None:
    template = go.layout.Template()
    template.layout = go.Layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, color="#C9D3E2", size=12),
        colorway=[CYAN, TEAL, AMBER, RED, "#9BA9C2", SLATE, "#B9C6D8"],
        xaxis=dict(gridcolor=RULE, zerolinecolor=RULE, linecolor=RULE, tickcolor=RULE),
        yaxis=dict(gridcolor=RULE, zerolinecolor="#2A3D5C", linecolor=RULE, tickcolor=RULE),
        hoverlabel=dict(bgcolor=PANEL_2, bordercolor=RULE, font=dict(family=FONT, color=TEXT, size=12)),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=MUTED)),
        margin=dict(l=10, r=10, t=36, b=10),
        title=dict(font=dict(size=14, color=TEXT), x=0, xanchor="left"),
    )
    pio.templates["sentinel"] = template
    pio.templates.default = "sentinel"
