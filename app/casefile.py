"""Self-contained HTML case file: entity graph (SVG), per-link evidence, rejected links. Print to PDF from the browser."""
from __future__ import annotations
import html
import math
import os

CASE_DIR = os.path.join(os.path.dirname(__file__), "..", "logs", "cases")
COLORS = {"shared_phone": "#d62839", "shared_vehicle": "#7b2cbf", "shared_address": "#f77f00", "shared_shop": "#8d99ae"}


def _graph_svg(ring: dict) -> str:
    claims = ring["claims"]
    cx, cy, r = 260, 230, 180
    pos = {c: (cx + r * math.cos(2 * math.pi * i / len(claims)), cy + r * math.sin(2 * math.pi * i / len(claims)))
           for i, c in enumerate(claims)}
    out = ['<svg viewBox="0 0 520 470" role="img" aria-label="Entity graph of the ring">']
    shops = sorted({str(l["value"]) for l in ring["links"] if l["strength"] == "weak"})
    for shop in shops[:1]:  # weak shop links are drawn as one hub, not a clique of lines
        for c, (x, y) in pos.items():
            out.append(f'<line x1="{cx}" y1="{cy}" x2="{x:.0f}" y2="{y:.0f}" stroke="{COLORS["shared_shop"]}" stroke-width="0.8" '
                       f'stroke-dasharray="4 4" opacity="0.5"/>')
        out.append(f'<rect x="{cx - 32}" y="{cy - 12}" width="64" height="24" rx="4" fill="#8d99ae"/>'
                   f'<text x="{cx}" y="{cy + 4}" font-size="11" text-anchor="middle" fill="#fff">shop {html.escape(shop)}</text>')
    for l in ring["links"]:
        if l["strength"] == "weak":
            continue
        (x1, y1), (x2, y2) = pos[l["a"]], pos[l["b"]]
        out.append(f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" stroke="{COLORS.get(l["kind"], "#555")}" '
                   f'stroke-width="1.8" opacity="0.8"><title>{html.escape(l["kind"])}: {html.escape(str(l["value"]))}</title></line>')
    for c, (x, y) in pos.items():
        who = ring["claim_people"].get(c, "")
        out.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="13" fill="#1d3557"><title>{html.escape(c)} {html.escape(who)}</title></circle>'
                   f'<text x="{x:.0f}" y="{y + 28:.0f}" font-size="9" text-anchor="middle" fill="currentColor">{html.escape(c)}</text>')
    out.append("</svg>")
    return "".join(out)


def render(trace_id: str, result: dict) -> str:
    n = result["narrative"]
    legend = "".join(f'<span><i style="background:{c}"></i>{k.replace("shared_", "")}</span>' for k, c in COLORS.items())
    rings = ""
    for r in result["rings"]:
        rows = "".join(
            f"<tr><td>{html.escape(l['kind'])}</td><td>{html.escape(l['a'])} / {html.escape(l['b'])}</td>"
            f"<td>{html.escape(str(l['value']))}</td><td>{l['strength']}</td><td><code>{html.escape(l['sql'][:160])}...</code></td></tr>"
            for l in r["links"])
        rings += (f"<section><h2>Ring {r['id']}: {len(r['claims'])} claims, {len(r['people'])} people, exposure {r['exposure']:,.2f}</h2>"
                  f"<div class=legend>{legend}<span>dashed spokes = shared repair shop (weak evidence)</span></div>{_graph_svg(r)}"
                  f"<p>People: {html.escape(', '.join(r['people']))}</p>"
                  f"<details><summary>Evidence for every link ({len(r['links'])})</summary><table><tr><th>Type</th><th>Claims</th><th>Value</th><th>Strength</th><th>Query</th></tr>{rows}</table></details></section>")
    rej = "".join(f"<tr><td>{html.escape(g['kind'])}</td><td>{html.escape(str(g['value']))}</td><td>{g['count']}</td><td>{html.escape(g['reason'])}</td></tr>"
                  for g in result["rejected"])
    leads = "".join(f"<li>Shop {html.escape(str(l['shop']))}: {', '.join(l['claims'])} ({html.escape(l['why'])})</li>" for l in result["unconfirmed_leads"])
    doubts = "".join(f"<li>{html.escape(d)}</li>" for d in result["critic_doubts"])
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ringbreaker case file {html.escape(trace_id)}</title>
<style>:root{{color-scheme:light dark}}body{{font:15px/1.5 system-ui,sans-serif;max-width:900px;margin:0 auto;padding:16px}}
svg{{width:100%;max-width:520px;color:inherit}}table{{border-collapse:collapse;width:100%;font-size:13px}}td,th{{border:1px solid #8884;padding:4px 6px;text-align:left;vertical-align:top}}
.legend{{display:flex;gap:12px;flex-wrap:wrap;font-size:12px}}.legend i{{display:inline-block;width:10px;height:10px;margin-right:4px}}
.note{{border-left:4px solid #f77f00;padding:6px 12px;background:#f77f0015}}code{{word-break:break-all}}</style></head><body>
<h1>{html.escape(str(n.get('headline', 'Case file')))}</h1>
{"".join(f'<p class=note><b>Warning:</b> {html.escape(w)}</p>' for w in result.get("warnings", []))}
<p class=note>Referral for human review. These are leads, not accusations. Every link below cites the query that found it.</p>
<p>{html.escape(str(n.get('summary', '')))}</p>
<p><b>Recommended action:</b> {html.escape(str(n.get('recommended_action', '')))}<br>
<b>Confidence:</b> {n.get('confidence')} ({html.escape(str(n.get('confidence_reasoning', '')))})</p>
{rings or '<p>No ring survived the Critic for this request.</p>'}
<h2>Rejected as coincidence</h2><table><tr><th>Type</th><th>Value</th><th>Links</th><th>Reason</th></tr>{rej}</table>
<h2>Unconfirmed leads</h2><ul>{leads or '<li>none</li>'}</ul>
<h2>Critic's remaining doubts</h2><ul>{doubts or '<li>none recorded</li>'}</ul>
<p><small>Trace: {html.escape(trace_id)} (logs/{html.escape(trace_id)}.jsonl). Synthetic data only.</small></p></body></html>"""


def write_case(trace_id: str, result: dict) -> str:
    os.makedirs(CASE_DIR, exist_ok=True)
    path = os.path.join(CASE_DIR, f"{trace_id}.html")
    with open(path, "w") as f:
        f.write(render(trace_id, result))
    return path
