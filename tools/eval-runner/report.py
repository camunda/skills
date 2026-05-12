"""Self-contained HTML reports for an eval iteration.

Two entry points:

    render_iteration(iteration_dir, repo_root) -> writes report.html
    render_index(skill_evals_dir) -> writes index.html

Both produce static HTML readable via ``file://`` with no server. BPMN/DMN
content is rendered client-side via ``bpmn-js`` loaded from a CDN with SRI
hashes pinned below; everything else (FEEL, JSON, plain text) is embedded
inline. Fallback text is shown if the CDN load fails so a stale report still
displays the raw content.

Upgrade dance for ``bpmn-js``:
    1. Bump BPMN_JS_VERSION below.
    2. curl the new bundle/css and recompute the SRI hashes:
        curl -sL https://cdn.jsdelivr.net/npm/bpmn-js@<v>/dist/bpmn-viewer.production.min.js \\
          | openssl dgst -sha384 -binary | openssl base64 -A
    3. Update BPMN_JS_*_SRI constants and re-run a sample iteration to verify.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import re
from pathlib import Path
from typing import Any

# --- Pinned external assets -------------------------------------------------

BPMN_JS_VERSION = "17.11.1"
BPMN_JS_BASE = f"https://cdn.jsdelivr.net/npm/bpmn-js@{BPMN_JS_VERSION}/dist"

BPMN_JS_SCRIPT_URL = f"{BPMN_JS_BASE}/bpmn-viewer.production.min.js"
BPMN_JS_SCRIPT_SRI = "sha384-RrNqnohpHKt52qR3noc7GV2JnuO3K15Se30/vbqSXHY4NiHt05RFbUXJ5gnz6R1D"

BPMN_JS_CSS_URL = f"{BPMN_JS_BASE}/assets/bpmn-js.css"
BPMN_JS_CSS_SRI = "sha384-d5fPuJ8qoomhVwsLNT3CIO4Wr1Ur5kNIP6IkZ1c1m5deqBd43hlGyuXPeFUiuA0N"

DIAGRAM_JS_CSS_URL = f"{BPMN_JS_BASE}/assets/diagram-js.css"
DIAGRAM_JS_CSS_SRI = "sha384-2WPRuHNLlqer/8fKQLOMZSWVINTz4vDTnIB1SXm75ubMI3oBGJyfvuOcPPc0Pfjh"

# --- Public API -------------------------------------------------------------


def render_iteration(iteration_dir: Path, repo_root: Path | None = None) -> Path:
    """Write ``iteration_dir/report.html`` and return its path."""
    summary = _read_json(iteration_dir / "summary.json") or {}
    cases = _collect_cases(iteration_dir)
    skill = summary.get("skill") or iteration_dir.parent.name
    needs_bpmn = any(
        out["type"] in ("bpmn", "dmn")
        for case in cases
        for cfg in case["configs"].values()
        for out in cfg["outputs"]
    )
    siblings = _sibling_iterations(iteration_dir)
    html_text = _render_iteration_html(skill, iteration_dir, summary, cases, needs_bpmn, siblings)
    out = iteration_dir / "report.html"
    out.write_text(html_text, encoding="utf-8")
    return out


def render_index(skill_evals_dir: Path) -> Path:
    """Write ``<skill_evals_dir>/index.html`` listing every iteration."""
    skill = skill_evals_dir.name
    rows = []
    iterations = sorted(
        (p for p in skill_evals_dir.iterdir() if p.is_dir() and p.name.startswith("iteration-")),
        key=_iteration_index,
    )
    for it in iterations:
        s = _read_json(it / "summary.json") or {}
        rows.append(
            {
                "name": it.name,
                "generated_at": s.get("generated_at", ""),
                "status": s.get("status", ""),
                "triggers_f1": _safe_get(s, "triggers", "f1"),
                "with_skill": _safe_get(s, "quality", "with_skill", "pass_rate"),
                "without_skill": _safe_get(s, "quality", "without_skill", "pass_rate"),
                "delta_pp": _safe_get(s, "quality", "delta_pp"),
                "git_head": s.get("git_head", ""),
            }
        )
    out = skill_evals_dir / "index.html"
    out.write_text(_render_index_html(skill, rows), encoding="utf-8")
    return out


# --- Iteration scanning -----------------------------------------------------


_RENDERABLE = {".bpmn", ".dmn"}
_SKIP = {".bpmnlintrc", ".gitkeep"}


def _collect_cases(iteration_dir: Path) -> list[dict[str, Any]]:
    """Walk iteration_dir/<arm>/<case-id>/outputs and collect rendering data."""
    arms = ("with_skill", "without_skill")
    cases_by_id: dict[str, dict[str, Any]] = {}
    for arm in arms:
        arm_dir = iteration_dir / arm
        if not arm_dir.is_dir():
            continue
        for case_dir in sorted(arm_dir.iterdir()):
            if not case_dir.is_dir():
                continue
            case = cases_by_id.setdefault(
                case_dir.name,
                {"id": case_dir.name, "prompt": "", "configs": {}},
            )
            outputs_dir = case_dir / "outputs"
            outputs: list[dict[str, Any]] = []
            if outputs_dir.is_dir():
                for f in sorted(outputs_dir.iterdir()):
                    if not f.is_file() or f.name in _SKIP or f.name.startswith("."):
                        continue
                    ext = f.suffix.lower()
                    typ = (
                        "bpmn" if ext == ".bpmn"
                        else "dmn" if ext == ".dmn"
                        else "form" if ext == ".form"
                        else "text"
                    )
                    try:
                        content = f.read_text(encoding="utf-8")
                    except UnicodeDecodeError:
                        content = "(binary file omitted)"
                    outputs.append({"name": f.name, "type": typ, "content": content})
                outputs.sort(key=lambda o: (0 if o["type"] in ("bpmn", "dmn") else 1, o["name"]))
            grading = _read_json(case_dir / "grading.json")
            timing = _read_json(case_dir / "timing.json")
            case["configs"][arm] = {"outputs": outputs, "grading": grading, "timing": timing}
        # Pick up case prompt from eval_metadata.json, written by the runner.
    for case_id, case in cases_by_id.items():
        for arm in arms:
            meta_path = iteration_dir / arm / case_id / "eval_metadata.json"
            meta = _read_json(meta_path)
            if meta and not case["prompt"]:
                case["prompt"] = meta.get("prompt", "")
                break
    return [cases_by_id[k] for k in sorted(cases_by_id)]


def _sibling_iterations(iteration_dir: Path) -> tuple[str | None, str | None]:
    parent = iteration_dir.parent
    iterations = sorted(
        (p.name for p in parent.iterdir() if p.is_dir() and p.name.startswith("iteration-")),
        key=lambda n: _iteration_index_from_name(n),
    )
    if iteration_dir.name not in iterations:
        return (None, None)
    i = iterations.index(iteration_dir.name)
    prev = iterations[i - 1] if i > 0 else None
    nxt = iterations[i + 1] if i + 1 < len(iterations) else None
    return (prev, nxt)


def _iteration_index(p: Path) -> int:
    return _iteration_index_from_name(p.name)


def _iteration_index_from_name(name: str) -> int:
    m = re.match(r"iteration-(\d+)$", name)
    return int(m.group(1)) if m else -1


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _safe_get(d: dict[str, Any], *keys: str) -> Any:
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


# --- HTML rendering ---------------------------------------------------------


def _render_iteration_html(
    skill: str,
    iteration_dir: Path,
    summary: dict[str, Any],
    cases: list[dict[str, Any]],
    needs_bpmn: bool,
    siblings: tuple[str | None, str | None],
) -> str:
    title = f"{skill} / {iteration_dir.name}"
    head_bpmn = _bpmn_head() if needs_bpmn else ""
    body = []
    body.append(_iteration_header_html(skill, iteration_dir, summary, siblings))
    body.append(_iteration_summary_html(summary))
    if not cases:
        body.append('<div class="empty">No case directories yet (dry-run scaffolding only).</div>')
    else:
        body.append('<div class="cases">')
        for case in cases:
            body.append(_case_section_html(case))
        body.append("</div>")
    body_str = "\n".join(body)

    bpmn_init = _bpmn_init_script() if needs_bpmn else ""

    return _PAGE_TEMPLATE.format(
        title=html.escape(title),
        head_extra=head_bpmn,
        styles=_STYLES,
        body=body_str,
        scripts=bpmn_init,
    )


def _iteration_header_html(
    skill: str,
    iteration_dir: Path,
    summary: dict[str, Any],
    siblings: tuple[str | None, str | None],
) -> str:
    prev, nxt = siblings
    nav_links = []
    if prev:
        nav_links.append(f'<a href="../{html.escape(prev)}/report.html">&larr; {html.escape(prev)}</a>')
    nav_links.append('<a href="../index.html">all iterations</a>')
    if nxt:
        nav_links.append(f'<a href="../{html.escape(nxt)}/report.html">{html.escape(nxt)} &rarr;</a>')
    nav = " &middot; ".join(nav_links)
    generated = html.escape(summary.get("generated_at", ""))
    git_head = html.escape(summary.get("git_head", ""))
    status = html.escape(summary.get("status", "")) or "&nbsp;"
    return f"""
<header class="page-header">
  <div class="page-title">
    <h1>{html.escape(skill)} <span class="muted">/ {html.escape(iteration_dir.name)}</span></h1>
    <div class="meta">{generated} &middot; <code>{git_head}</code> &middot; <span class="status">{status}</span></div>
  </div>
  <nav class="iter-nav">{nav}</nav>
</header>
""".strip()


def _iteration_summary_html(summary: dict[str, Any]) -> str:
    triggers = summary.get("triggers") or {}
    quality = summary.get("quality") or {}
    f1 = triggers.get("f1")
    with_skill = _safe_get(summary, "quality", "with_skill", "pass_rate")
    without_skill = _safe_get(summary, "quality", "without_skill", "pass_rate")
    delta = quality.get("delta_pp")

    def stat(label: str, value: Any, fmt: str = "{:.2f}") -> str:
        if value is None:
            disp = "&mdash;"
        else:
            try:
                disp = fmt.format(value)
            except (TypeError, ValueError):
                disp = html.escape(str(value))
        return f'<div class="stat"><div class="label">{label}</div><div class="value">{disp}</div></div>'

    return f"""
<section class="summary">
  {stat("trigger F1", f1)}
  {stat("with_skill", with_skill)}
  {stat("without_skill", without_skill)}
  {stat("&Delta; pp", delta)}
</section>
""".strip()


def _case_section_html(case: dict[str, Any]) -> str:
    case_id = html.escape(case["id"])
    prompt = html.escape(case.get("prompt", "")).replace("\n", "<br>")
    arms = ("with_skill", "without_skill")
    panels = []
    for arm in arms:
        cfg = case["configs"].get(arm)
        if cfg is None:
            panels.append(f'<div class="panel"><h3>{arm}</h3><div class="empty">no data</div></div>')
            continue
        panels.append(_panel_html(case_id, arm, cfg))
    panels_html = "\n".join(panels)
    return f"""
<section class="case" id="case-{case_id}">
  <h2>{case_id}</h2>
  {('<p class="prompt">' + prompt + '</p>') if prompt else ''}
  <div class="panels">{panels_html}</div>
</section>
""".strip()


def _panel_html(case_id: str, arm: str, cfg: dict[str, Any]) -> str:
    outputs = cfg.get("outputs") or []
    timing = cfg.get("timing") or {}
    grading = cfg.get("grading") or {}
    timing_meta = ""
    if timing:
        tokens = timing.get("total_tokens", 0)
        dur = timing.get("total_duration_seconds", 0)
        timing_meta = f'<span class="meta">{tokens:,} tokens &middot; {dur:.1f}s</span>'

    if not outputs:
        outputs_html = '<div class="no-output">No output files</div>'
    else:
        tabs = []
        bodies = []
        for i, out in enumerate(outputs):
            tab_id = f"{case_id}-{arm}-{i}"
            active = " active" if i == 0 else ""
            tabs.append(
                f'<button class="file-tab{active}" data-target="{tab_id}">{html.escape(out["name"])}</button>'
            )
            display = "" if i == 0 else "display:none;"
            if out["type"] in ("bpmn", "dmn"):
                bodies.append(
                    f'<div class="canvas" id="canvas-{tab_id}" data-bpmn="{html.escape(out["content"], quote=True)}" style="{display}"></div>'
                )
            else:
                bodies.append(
                    f'<pre class="text-output" id="text-{tab_id}" style="{display}">{html.escape(out["content"])}</pre>'
                )
        outputs_html = (
            f'<div class="file-tabs">{"".join(tabs)}</div>'
            if len(outputs) > 1
            else ""
        ) + "\n".join(bodies)

    grading_html = _grading_html(grading) if grading else ""

    return f"""
<div class="panel">
  <div class="panel-header"><h3>{arm}</h3>{timing_meta}</div>
  {outputs_html}
  {grading_html}
</div>
""".strip()


def _grading_html(grading: dict[str, Any]) -> str:
    expectations = grading.get("expectations") or []
    if not expectations:
        return ""
    summary = grading.get("summary") or {}
    passed = summary.get("passed", 0)
    total = summary.get("total", len(expectations))
    rows = []
    for exp in expectations:
        ok = bool(exp.get("passed"))
        cls = "pass" if ok else "fail"
        letter = "P" if ok else "F"
        evidence = (
            f'<div class="evidence">{html.escape(str(exp.get("evidence", "")))}</div>'
            if exp.get("evidence") else ""
        )
        rows.append(
            f'<div class="assertion"><div class="icon {cls}">{letter}</div>'
            f'<div class="text">{html.escape(str(exp.get("text", "")))}{evidence}</div></div>'
        )
    return f'<div class="grading"><h4>Assertions ({passed}/{total})</h4>{"".join(rows)}</div>'


def _bpmn_head() -> str:
    return f"""
<link rel="stylesheet" href="{BPMN_JS_CSS_URL}" integrity="{BPMN_JS_CSS_SRI}" crossorigin="anonymous">
<link rel="stylesheet" href="{DIAGRAM_JS_CSS_URL}" integrity="{DIAGRAM_JS_CSS_SRI}" crossorigin="anonymous">
""".strip()


def _bpmn_init_script() -> str:
    return f"""
<script src="{BPMN_JS_SCRIPT_URL}" integrity="{BPMN_JS_SCRIPT_SRI}" crossorigin="anonymous"
  onerror="document.querySelectorAll('.canvas').forEach(c => {{ c.classList.add('cdn-fail'); c.textContent = 'bpmn-js failed to load from CDN. Open the .bpmn file directly to inspect.'; }});"></script>
<script>
  document.querySelectorAll('.canvas').forEach(function(el) {{
    if (typeof BpmnJS === 'undefined') return;
    var xml = el.getAttribute('data-bpmn');
    var viewer = new BpmnJS({{ container: el }});
    viewer.importXML(xml).then(function() {{ viewer.get('canvas').zoom('fit-viewport'); }})
      .catch(function(err) {{ el.classList.add('render-error'); el.textContent = 'Render error: ' + err.message; }});
  }});
  document.querySelectorAll('.file-tab').forEach(function(tab) {{
    tab.addEventListener('click', function() {{
      var target = tab.getAttribute('data-target');
      var panel = tab.closest('.panel');
      panel.querySelectorAll('.file-tab').forEach(function(t) {{ t.classList.toggle('active', t === tab); }});
      panel.querySelectorAll('.canvas, .text-output').forEach(function(el) {{
        var id = el.id.replace(/^(canvas|text)-/, '');
        el.style.display = (id === target) ? '' : 'none';
      }});
    }});
  }});
</script>
""".strip()


def _render_index_html(skill: str, rows: list[dict[str, Any]]) -> str:
    body = [f"<h1>{html.escape(skill)} &mdash; iterations</h1>"]
    if not rows:
        body.append('<p class="empty">No iterations yet.</p>')
    else:
        body.append('<table class="iterations">')
        body.append(
            "<thead><tr><th>iteration</th><th>generated</th>"
            "<th>F1</th><th>with</th><th>without</th><th>&Delta;pp</th>"
            "<th>git</th><th>status</th></tr></thead><tbody>"
        )
        for r in rows:
            f1 = "&mdash;" if r["triggers_f1"] is None else f"{r['triggers_f1']:.2f}"
            ws = "&mdash;" if r["with_skill"] is None else f"{r['with_skill']:.2f}"
            wos = "&mdash;" if r["without_skill"] is None else f"{r['without_skill']:.2f}"
            dpp = "&mdash;" if r["delta_pp"] is None else f"{r['delta_pp']:+.1f}"
            body.append(
                f'<tr><td><a href="{html.escape(r["name"])}/report.html">{html.escape(r["name"])}</a></td>'
                f'<td class="muted">{html.escape(r["generated_at"])}</td>'
                f"<td>{f1}</td><td>{ws}</td><td>{wos}</td><td>{dpp}</td>"
                f'<td><code>{html.escape(r["git_head"])}</code></td>'
                f'<td>{html.escape(r["status"])}</td></tr>'
            )
        body.append("</tbody></table>")
    body.append(
        f'<p class="footer muted">Generated {html.escape(dt.datetime.now(dt.timezone.utc).isoformat())}</p>'
    )
    return _PAGE_TEMPLATE.format(
        title=html.escape(f"{skill} — iterations"),
        head_extra="",
        styles=_STYLES,
        body="\n".join(body),
        scripts="",
    )


# --- Templates --------------------------------------------------------------

_STYLES = """
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       margin: 0; background: #f5f5f5; color: #222; }
.page-header { background: #1a1a2e; color: #fff; padding: 14px 24px;
               display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.page-header h1 { margin: 0; font-size: 18px; font-weight: 600; }
.page-header .muted { color: #aaa; font-weight: 400; }
.page-header .meta { font-size: 12px; color: #aaa; margin-top: 2px; }
.page-header .status { color: #f59e0b; }
.iter-nav a { color: #fc5d0d; text-decoration: none; margin: 0 4px; }
.iter-nav a:hover { text-decoration: underline; }
.summary { display: flex; gap: 24px; padding: 14px 24px; background: #fff;
           border-bottom: 1px solid #ddd; font-size: 13px; }
.stat .label { color: #888; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }
.stat .value { font-size: 16px; font-weight: 600; }
.cases { padding: 16px 24px; }
.case { background: #fff; border: 1px solid #ddd; border-radius: 4px; margin-bottom: 16px; overflow: hidden; }
.case h2 { font-size: 14px; padding: 10px 14px; margin: 0; background: #f0f0f0;
           border-bottom: 1px solid #ddd; font-family: ui-monospace, Menlo, monospace; }
.case .prompt { padding: 10px 14px; font-size: 13px; color: #555; border-bottom: 1px solid #eee; }
.panels { display: flex; min-height: 320px; }
.panel { flex: 1; display: flex; flex-direction: column; border-right: 1px solid #eee; min-width: 0; }
.panel:last-child { border-right: none; }
.panel-header { background: #fafafa; padding: 8px 14px; font-size: 13px; font-weight: 600;
                border-bottom: 1px solid #eee; display: flex; justify-content: space-between; }
.panel-header h3 { margin: 0; font-size: 13px; }
.panel-header .meta { font-weight: 400; color: #888; font-size: 11px; }
.canvas { flex: 1; min-height: 280px; background: #fff; }
.canvas.cdn-fail, .canvas.render-error { padding: 16px; color: #991b1b; font-size: 12px;
                                          background: #fef2f2; }
.text-output { flex: 1; margin: 0; padding: 12px 14px; background: #fff; overflow: auto;
               font-family: ui-monospace, Menlo, monospace; font-size: 12px; white-space: pre-wrap;
               word-break: break-word; }
.file-tabs { display: flex; gap: 1px; background: #e5e5e5; }
.file-tab { padding: 4px 10px; font-size: 11px; cursor: pointer; background: #f4f4f4;
            border: none; color: #555; }
.file-tab:hover { background: #ececec; }
.file-tab.active { background: #fff; color: #222; font-weight: 600; }
.no-output { padding: 20px; color: #999; font-size: 13px; text-align: center; }
.grading { background: #fafafa; border-top: 1px solid #eee; padding: 10px 14px; }
.grading h4 { margin: 0 0 8px; font-size: 11px; text-transform: uppercase; color: #666;
              letter-spacing: 0.5px; }
.assertion { display: flex; gap: 8px; align-items: flex-start; padding: 4px 0;
             font-size: 12px; border-bottom: 1px solid #f0f0f0; }
.assertion:last-child { border-bottom: none; }
.assertion .icon { width: 18px; height: 18px; border-radius: 50%; flex-shrink: 0;
                   display: flex; align-items: center; justify-content: center;
                   font-size: 10px; font-weight: 700; }
.assertion .icon.pass { background: #dcfce7; color: #166534; }
.assertion .icon.fail { background: #fecaca; color: #991b1b; }
.assertion .evidence { color: #888; font-size: 11px; margin-top: 2px; }
.empty { padding: 24px; text-align: center; color: #999; }
.iterations { width: 100%; border-collapse: collapse; margin: 16px 24px; background: #fff;
              border: 1px solid #ddd; }
.iterations th, .iterations td { padding: 8px 12px; text-align: left; border-bottom: 1px solid #eee;
                                  font-size: 13px; }
.iterations th { background: #f0f0f0; font-size: 11px; text-transform: uppercase;
                 color: #666; letter-spacing: 0.5px; }
.iterations a { color: #fc5d0d; text-decoration: none; }
.iterations a:hover { text-decoration: underline; }
.muted { color: #888; }
.footer { padding: 12px 24px; font-size: 11px; }
"""

_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
{head_extra}
<style>{styles}</style>
</head>
<body>
{body}
{scripts}
</body>
</html>
"""
