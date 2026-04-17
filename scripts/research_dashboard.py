#!/usr/bin/env python3
from __future__ import annotations

import argparse
import errno
import html
import json
import sys
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.research_agent_cli import load_project_config
from scripts.research_loop_contract import (
    bootstrap_state_artifacts,
    load_agent_observability,
    load_run_state,
    overlay_observability_sidecars,
    read_json,
    write_pending_human_prompt,
)

DASHBOARD_TITLE = "sub-PHD"
BEIJING_TZ = timezone(timedelta(hours=8))


def load_dashboard_state(observability_path: Path, run_state_path: Path) -> dict[str, Any]:
    try:
        observability = load_agent_observability(observability_path)
    except Exception:
        observability = read_json(observability_path) if observability_path.exists() else {"segments": []}
    observability = overlay_observability_sidecars(observability)
    try:
        run_state = load_run_state(run_state_path)
    except Exception:
        run_state = read_json(run_state_path) if run_state_path.exists() else {}
    return {
        "segments": observability.get("segments", []),
        "pending_human_prompt": run_state.get("pending_human_prompt"),
        "last_applied_human_prompt": run_state.get("last_applied_human_prompt"),
        "phase": run_state.get("phase"),
        "next_action": run_state.get("next_action"),
        "reader_iteration": run_state.get("reader_iteration"),
        "reader_iteration_cap": run_state.get("reader_iteration_cap"),
        "runner_iteration": run_state.get("runner_iteration"),
        "runner_iteration_cap": run_state.get("runner_iteration_cap"),
    }


def build_gantt_rows(observability: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for segment in observability.get("segments", []):
        rows.append(
            {
                "role": segment.get("role", ""),
                "task": segment.get("task", ""),
                "started_at": segment.get("started_at", ""),
                "ended_at": segment.get("ended_at"),
                "eta": segment.get("eta", ""),
                "expected_output": segment.get("expected_output", ""),
                "why": segment.get("why", ""),
                "status": segment.get("status", ""),
                "completion_summary": segment.get("completion_summary", ""),
            }
        )
    return rows


def _sort_rows_for_display(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def sort_key(row: dict[str, Any]) -> tuple[int, str]:
        started = str(row.get("started_at", "") or "")
        if not started:
            return (1, "")
        try:
            normalized = started.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
            return (0, parsed.isoformat())
        except ValueError:
            return (0, started)

    return sorted(rows, key=sort_key)


def _parse_iso8601(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _format_duration(start: datetime | None, end: datetime | None) -> str:
    if not start or not end:
        return "n/a"
    total_seconds = max(0, int((end - start).total_seconds()))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _format_dashboard_timestamp(value: str | None, *, active_fallback: str = "Active") -> str:
    parsed = _parse_iso8601(value)
    if not parsed:
        return active_fallback
    return parsed.astimezone(BEIJING_TZ).strftime("%m-%dT%H:%M")


def build_dashboard_html(
    *,
    rows: list[dict[str, Any]],
    pending_prompt: dict[str, Any] | None,
    last_launch_metadata: dict[str, Any] | None = None,
    title: str = DASHBOARD_TITLE,
) -> str:
    return render_dashboard_html(
        {
            "rows": rows,
            "pending_human_prompt": pending_prompt,
            "last_applied_human_prompt": last_launch_metadata or {},
        },
        title=title,
    )


def render_dashboard_html(state: dict[str, Any], title: str = DASHBOARD_TITLE) -> str:
    segments = _sort_rows_for_display(state.get("rows") or build_gantt_rows({"segments": state.get("segments", [])}))
    pending = state.get("pending_human_prompt") or {}
    consumed = state.get("last_applied_human_prompt") or {}
    active_count = sum(1 for segment in segments if str(segment.get("status", "")).lower() in {"running", "pending"})
    phase = str(state.get("phase", "idle") or "idle")
    is_runner_lane = phase in {"runner", "watch"}
    current_iteration = state.get("runner_iteration") if is_runner_lane else state.get("reader_iteration")
    current_iteration_cap = state.get("runner_iteration_cap") if is_runner_lane else state.get("reader_iteration_cap")
    current_segment = segments[-1] if segments else {}
    started_dt = _parse_iso8601(str(current_segment.get("started_at", "") or ""))
    eta_dt = _parse_iso8601(str(current_segment.get("eta", "") or ""))
    now_dt = datetime.now(timezone.utc)
    run_elapsed = _format_duration(started_dt, now_dt)
    run_total = _format_duration(started_dt, eta_dt) if started_dt and eta_dt else "n/a"
    card_html: list[str] = []
    for index, segment in enumerate(segments):
        role = html.escape(str(segment.get("role", "") or "unknown"))
        task = html.escape(str(segment.get("task", "") or "Awaiting agent-authored task"))
        started = html.escape(_format_dashboard_timestamp(str(segment.get("started_at", "") or ""), active_fallback="-"))
        ended = html.escape(_format_dashboard_timestamp(str(segment.get("ended_at", "") or ""), active_fallback="Active"))
        eta = html.escape(_format_dashboard_timestamp(str(segment.get("eta", "") or ""), active_fallback="TBD"))
        expected_output = html.escape(str(segment.get("expected_output", "") or "Pending sidecar"))
        why = html.escape(str(segment.get("why", "") or "Pending sidecar"))
        completion_summary = html.escape(str(segment.get("completion_summary", "") or ""))
        lane = "signal" if str(segment.get("role", "")).lower() == "runner" else "editorial"
        focus = " current-focus" if index == len(segments) - 1 else ""
        focus_label = '<span class="current-focus-label">Current</span>' if focus else ''
        completion_block = (
            f"""
                  <div class="detail-block completion-block">
                    <span>Completion</span>
                    <strong>{completion_summary}</strong>
                  </div>
            """
            if completion_summary
            else ""
        )
        card_html.append(
            f"""
            <article class="timeline-item {lane}{focus}">
              <div class="lane-pin"></div>
              <div class="timeline-main">
                <div class="timeline-topline">
                  <span class="timeline-index">#{index + 1:02d}</span>
                  <span class="timeline-role">{role}</span>
                  {focus_label}
                </div>
                <h3 class="task-primary">{task}</h3>
                <div class="meta-inline">
                  <span><strong>Started</strong> {started}</span>
                  <span><strong>Ended</strong> {ended}</span>
                  <span><strong>ETA</strong> {eta}</span>
                  <span><strong>Role</strong> {role}</span>
                </div>
                <div class="detail-grid">
                  <div class="detail-block">
                    <span>Expected</span>
                    <strong>{expected_output}</strong>
                  </div>
                  <div class="detail-block">
                    <span>Why</span>
                    <strong>{why}</strong>
                  </div>
                  {completion_block}
                </div>
              </div>
            </article>
            """
        )

    pending_target = html.escape(str(pending.get("target", "none") or "none"))
    consumed_role = html.escape(str(consumed.get("applied_role", "none") or "none"))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      --page-bg: #0b1016;
      --panel-bg: rgba(10, 17, 26, 0.78);
      --panel-border: rgba(151, 255, 223, 0.16);
      --text-main: #eef7ff;
      --text-muted: rgba(217, 235, 255, 0.68);
      --accent: #86ffd6;
      --accent-strong: #38d9ff;
      --hero-bg: radial-gradient(circle at top right, rgba(56,217,255,0.16), transparent 28%), linear-gradient(135deg, rgba(8,14,22,0.92), rgba(13,23,35,0.82));
      --chip-bg: rgba(255,255,255,0.06);
      --timeline-line: linear-gradient(180deg, rgba(134,255,214,0.18), rgba(56,217,255,0.6));
      --input-bg: rgba(18, 28, 40, 0.96);
      --input-border: rgba(134,255,214,0.36);
      --shadow-soft: 0 24px 80px rgba(0, 0, 0, 0.35);
      --font-display: "Georgia", "Times New Roman", serif;
      --font-body: "Segoe UI", "Helvetica Neue", sans-serif;
    }}
    body.theme-editorial {{
      --page-bg: #f4efe7;
      --panel-bg: rgba(255, 252, 247, 0.92);
      --panel-border: rgba(70, 77, 92, 0.12);
      --text-main: #15181f;
      --text-muted: rgba(34, 38, 45, 0.58);
      --accent: #3e6f78;
      --accent-strong: #8b6348;
      --hero-bg: radial-gradient(circle at top left, rgba(139,99,72,0.12), transparent 26%), linear-gradient(135deg, rgba(255,251,245,0.94), rgba(242,235,225,0.92));
      --chip-bg: rgba(28, 33, 41, 0.06);
      --timeline-line: linear-gradient(180deg, rgba(62,111,120,0.18), rgba(139,99,72,0.55));
      --input-bg: rgba(255,255,255,0.98);
      --input-border: rgba(62,111,120,0.28);
      --shadow-soft: 0 24px 70px rgba(77, 67, 52, 0.12);
      --font-display: "Baskerville", "Georgia", serif;
      --font-body: "Trebuchet MS", "Gill Sans", sans-serif;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      font-family: var(--font-body);
      color: var(--text-main);
      background:
        radial-gradient(circle at 20% 10%, rgba(56, 217, 255, 0.09), transparent 26%),
        radial-gradient(circle at 80% 0%, rgba(134,255,214,0.12), transparent 24%),
        var(--page-bg);
      transition: background 220ms ease, color 220ms ease;
    }}
    body::before {{
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background-image:
        linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px);
      background-size: 40px 40px;
      opacity: 0.35;
      mix-blend-mode: soft-light;
    }}
    .page-shell {{
      position: relative;
      padding: 18px;
      display: grid;
      grid-template-columns: minmax(0, 1.78fr) minmax(270px, 0.62fr);
      gap: 12px;
      min-height: 100vh;
    }}
    .hero-panel, .summary-strip, .timeline-shell, .panel {{
      border: 1px solid var(--panel-border);
      background: var(--panel-bg);
      backdrop-filter: blur(18px);
      box-shadow: var(--shadow-soft);
      border-radius: 20px;
    }}
    .hero-panel {{
      background: var(--hero-bg);
      padding: 16px 18px;
    }}
    .hero-top {{
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: flex-start;
    }}
    .brand-mark {{
      display: inline-flex;
      align-items: center;
      gap: 10px;
      padding: 8px 12px;
      border-radius: 999px;
      background: rgba(255,255,255,0.06);
      color: var(--text-muted);
      letter-spacing: 0.16em;
      text-transform: uppercase;
      font-size: 11px;
    }}
    .brand-mark strong {{
      color: var(--text-main);
      font-family: var(--font-display);
      font-size: 18px;
      letter-spacing: 0.08em;
    }}
    .theme-toggle {{
      display: inline-flex;
      gap: 8px;
      padding: 7px;
      border-radius: 999px;
      background: rgba(255,255,255,0.06);
      border: 1px solid rgba(255,255,255,0.08);
    }}
    .theme-button {{
      border: 0;
      border-radius: 999px;
      padding: 8px 13px;
      font: inherit;
      color: var(--text-muted);
      background: transparent;
      cursor: pointer;
      transition: transform 150ms ease, background 150ms ease, color 150ms ease;
    }}
    .theme-button.active {{
      background: rgba(255,255,255,0.14);
      color: var(--text-main);
      transform: translateY(-1px);
    }}
    .summary-strip {{
      margin-top: 12px;
      padding: 10px;
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 8px;
    }}
    .status-card {{
      padding: 10px 12px;
      border-radius: 14px;
      background: var(--chip-bg);
      border: 1px solid rgba(255,255,255,0.08);
    }}
    .status-card span {{
      display: block;
      color: var(--text-muted);
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: 0.12em;
    }}
    .status-card strong {{
      display: block;
      margin-top: 4px;
      font-size: 15px;
      font-family: var(--font-display);
    }}
    .panel {{
      padding: 14px;
      display: flex;
      flex-direction: column;
      gap: 10px;
      align-self: start;
      position: sticky;
      top: 18px;
    }}
    .panel-head {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 10px;
    }}
    .panel-head h2 {{
      margin: 0;
      font-family: var(--font-display);
      font-size: 19px;
    }}
    .panel-head p, .panel small, .status-copy {{
      margin: 0;
      color: var(--text-muted);
      line-height: 1.45;
      font-size: 12px;
    }}
    .status-pill {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 10px;
      border-radius: 999px;
      background: var(--chip-bg);
      color: var(--text-muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.1em;
    }}
    .status-dot {{
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: linear-gradient(135deg, var(--accent), var(--accent-strong));
      box-shadow: 0 0 18px rgba(56,217,255,0.45);
    }}
    label {{
      display: block;
      color: var(--text-muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.14em;
      margin-bottom: 6px;
    }}
    textarea, select, button {{ font: inherit; }}
    textarea, select {{
      width: 100%;
      border-radius: 14px;
      border: 1px solid var(--input-border);
      padding: 10px 12px;
      background: var(--input-bg);
      color: var(--text-main);
      outline: none;
      box-shadow: inset 0 0 0 1px rgba(255,255,255,0.05);
      transition: border-color 160ms ease, box-shadow 160ms ease, background 160ms ease;
    }}
    textarea:focus, select:focus {{
      border-color: var(--accent-strong);
      box-shadow: 0 0 0 3px rgba(56,217,255,0.18);
    }}
    textarea {{
      min-height: 82px;
      resize: vertical;
      line-height: 1.55;
    }}
    .panel-actions {{
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
    }}
    .apply-button {{
      border: 0;
      border-radius: 999px;
      padding: 10px 14px;
      background: linear-gradient(135deg, var(--accent), var(--accent-strong));
      color: #061019;
      font-weight: 700;
      cursor: pointer;
      box-shadow: 0 12px 40px rgba(56,217,255,0.24);
    }}
    .status-copy {{
      display: grid;
      gap: 6px;
      padding: 12px 14px;
      border-radius: 14px;
      background: var(--chip-bg);
    }}
    .timeline-shell {{
      padding: 14px;
      margin-top: 10px;
    }}
    .timeline-shell h2 {{
      margin: 0;
      font-family: var(--font-display);
      font-size: 21px;
    }}
    .timeline-intro {{
      margin: 6px 0 10px;
      color: var(--text-muted);
      max-width: 78ch;
      line-height: 1.45;
      font-size: 12px;
    }}
    .timeline-list {{
      display: grid;
      gap: 7px;
    }}
    .timeline-item {{
      position: relative;
      display: block;
      border-radius: 15px;
      padding: 10px 12px 10px 18px;
      background: linear-gradient(180deg, rgba(255,255,255,0.05), rgba(255,255,255,0.02));
      border: 1px solid rgba(255,255,255,0.08);
      overflow: hidden;
    }}
    .timeline-item > * {{
      min-width: 0;
    }}
    .timeline-item.editorial {{
      background: linear-gradient(180deg, rgba(255,255,255,0.06), rgba(255,255,255,0.02));
    }}
    .timeline-item.current-focus {{
      border-color: rgba(134,255,214,0.4);
      box-shadow: 0 0 0 1px rgba(134,255,214,0.16), 0 18px 56px rgba(56,217,255,0.14);
      transform: translateY(1px);
      background: linear-gradient(180deg, rgba(134,255,214,0.08), rgba(255,255,255,0.03));
    }}
    body.theme-editorial .timeline-item.current-focus {{
      border-color: rgba(62,111,120,0.28);
      box-shadow: 0 0 0 1px rgba(62,111,120,0.12), 0 18px 56px rgba(139,99,72,0.08);
    }}
    .lane-pin {{
      position: absolute;
      inset: 10px auto 10px 9px;
      width: 4px;
      border-radius: 999px;
      background: var(--timeline-line);
    }}
    .timeline-main {{
      width: 100%;
      min-width: 0;
      padding-left: 4px;
    }}
    .timeline-topline {{
      display: flex;
      gap: 6px;
      align-items: center;
      flex-wrap: wrap;
      margin-bottom: 6px;
      color: var(--text-muted);
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: 0.12em;
    }}
    .timeline-role, .timeline-index, .current-focus-label {{
      padding: 4px 7px;
      border-radius: 999px;
      background: var(--chip-bg);
    }}
    .current-focus-label {{
      color: var(--text-main);
      background: rgba(134,255,214,0.14);
      border: 1px solid rgba(134,255,214,0.18);
    }}
    body.theme-editorial .current-focus-label {{
      background: rgba(62,111,120,0.12);
      border-color: rgba(62,111,120,0.18);
    }}
    .task-primary {{
      margin: 0;
      max-width: 100%;
      font-size: 20px;
      line-height: 1.12;
      font-family: var(--font-display);
      overflow-wrap: anywhere;
    }}
    .meta-inline {{
      margin-top: 6px;
      display: grid;
      grid-template-columns: repeat(4, minmax(108px, auto));
      gap: 6px 12px;
      color: var(--text-muted);
      font-size: 11px;
    }}
    .meta-inline span {{
      min-width: 0;
    }}
    .meta-inline strong {{
      color: var(--text-main);
      font-weight: 600;
      margin-right: 5px;
    }}
    .detail-grid {{
      margin-top: 7px;
      display: grid;
      grid-template-columns: repeat(2, minmax(220px, 1fr));
      gap: 8px;
    }}
    .detail-block {{
      padding: 8px 10px;
      border-radius: 11px;
      background: var(--chip-bg);
      border: 1px solid rgba(255,255,255,0.08);
    }}
    .completion-block {{
      grid-column: 1 / -1;
    }}
    .detail-block span {{
      display: block;
      color: var(--text-muted);
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: 0.14em;
    }}
    .detail-block strong {{
      display: block;
      margin-top: 4px;
      font-size: 12px;
      line-height: 1.4;
      color: var(--text-main);
    }}
    @media (max-width: 1080px) {{
      .page-shell {{ grid-template-columns: 1fr; }}
      .summary-strip {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
      .panel {{ position: static; }}
      .meta-inline {{ grid-template-columns: repeat(2, minmax(120px, 1fr)); }}
    }}
    @media (max-width: 720px) {{
      .page-shell {{ padding: 12px; }}
      .summary-strip {{ grid-template-columns: 1fr; }}
      .hero-top {{ flex-direction: column; }}
      .theme-toggle {{ width: 100%; justify-content: space-between; }}
      .timeline-item {{ padding-left: 14px; }}
      .lane-pin {{ inset: 10px auto 10px 7px; width: 3px; }}
      .meta-inline {{ grid-template-columns: 1fr; }}
      .detail-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body class="theme-signal">
  <div class="page-shell">
    <main>
      <section class="hero-panel">
        <div class="hero-top">
          <div class="brand-mark"><span>Research cockpit</span><strong>{html.escape(title)}</strong></div>
          <div class="theme-toggle" aria-label="Theme switcher">
            <button class="theme-button active" data-theme="theme-signal">Signal</button>
            <button class="theme-button" data-theme="theme-editorial">Editorial</button>
          </div>
        </div>
        <div class="summary-strip">
          <div class="status-card"><span>Current phase</span><strong>{html.escape(str(state.get('phase', 'idle') or 'idle'))}</strong></div>
          <div class="status-card"><span>Next action</span><strong>{html.escape(str(state.get('next_action', 'idle') or 'idle'))}</strong></div>
          <div class="status-card"><span>Active lanes</span><strong>{active_count}</strong></div>
          <div class="status-card"><span>Pending prompt</span><strong>{pending_target}</strong></div>
          <div class="status-card"><span>Current iteration</span><strong>{html.escape(str(current_iteration or 0))}/{html.escape(str(current_iteration_cap or 0))}</strong></div>
          <div class="status-card"><span>Run time</span><strong>{html.escape(run_elapsed)} / {html.escape(run_total)}</strong></div>
        </div>
      </section>

      <section class="timeline-shell">
        <h2>Timeline Board</h2>
        <p class="timeline-intro">Single-column, time-ordered, compact. The oldest tasks stay at the top, and the newest current task stays at the bottom near the one-time prompt panel. No fake progress bars.</p>
        <div class="timeline-list">
          {''.join(card_html) if card_html else '<article class="timeline-item editorial current-focus"><div class="lane-pin"></div><div class="timeline-main"><div class="timeline-topline"><span class="current-focus-label">Current</span></div><h3 class="task-primary">No active segments yet</h3><div class="detail-grid"><div class="detail-block"><span>Why</span><strong>Launch a reader or runner turn to let `sub-PHD` paint the first timeline item.</strong></div><div class="detail-block"><span>Expected</span><strong>The first observability segment will appear here.</strong></div></div></div></article>'}
        </div>
      </section>
    </main>

    <aside class="panel">
      <div class="panel-head">
        <div>
          <h2>Next Agent Prompt</h2>
          <p>Queue a one-shot intervention without breaking the current control loop.</p>
        </div>
        <div class="status-pill"><span class="status-dot"></span>manual override</div>
      </div>
      <div>
        <label for="prompt-text">One-time prompt</label>
        <textarea id="prompt-text" placeholder="Shape the next launch with a precise intervention."></textarea>
      </div>
      <div>
        <label for="prompt-target">Target</label>
        <select id="prompt-target">
          <option value="reader">reader</option>
          <option value="runner">runner</option>
          <option value="next_actual_agent">next_actual_agent</option>
        </select>
      </div>
      <div class="panel-actions">
        <button class="apply-button" id="apply-prompt">Apply One-Time Prompt</button>
        <small>Stored locally in the control truth, consumed once.</small>
      </div>
      <div class="status-copy">
        <p id="pending-state">Pending target: {pending_target}</p>
        <p id="consumed-state">Last consumed by: {consumed_role}</p>
      </div>
    </aside>
  </div>
  <script>
    const themeKey = 'subphd-theme';
    const body = document.body;
    const themeButtons = Array.from(document.querySelectorAll('.theme-button'));
    const applyTheme = (theme) => {{
      body.classList.remove('theme-signal', 'theme-editorial');
      body.classList.add(theme);
      themeButtons.forEach((button) => {{
        button.classList.toggle('active', button.dataset.theme === theme);
      }});
      localStorage.setItem(themeKey, theme);
    }};
    applyTheme(localStorage.getItem(themeKey) || 'theme-signal');
    themeButtons.forEach((button) => {{
      button.addEventListener('click', () => applyTheme(button.dataset.theme));
    }});
    const button = document.getElementById('apply-prompt');
    button?.addEventListener('click', async () => {{
      const text = document.getElementById('prompt-text').value;
      const target = document.getElementById('prompt-target').value;
      const res = await fetch('/api/prompt', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ text, target }})
      }});
      const payload = await res.json();
      document.getElementById('pending-state').textContent = 'Pending target: ' + (payload.pending_human_prompt?.target || 'none');
    }});
  </script>
</body>
</html>"""


def queue_one_time_prompt(root: Path, *, target: str, text: str, created_by: str = "dashboard") -> dict[str, Any]:
    config = load_project_config(root)
    paths = bootstrap_state_artifacts(root, config)
    return write_pending_human_prompt(paths.run_state, target=target, text=text, created_by=created_by)


class DashboardHandler(BaseHTTPRequestHandler):
    root: Path = Path(".")

    def _write_json(self, payload: dict[str, Any], status: int = 200) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # pragma: no cover
        config = load_project_config(self.root)
        paths = bootstrap_state_artifacts(self.root, config)
        if self.path == "/api/state":
            self._write_json(load_dashboard_state(paths.agent_observability, paths.run_state))
            return
        dashboard_state = load_dashboard_state(paths.agent_observability, paths.run_state)
        html_text = build_dashboard_html(
            rows=build_gantt_rows({"segments": dashboard_state.get("segments", [])}),
            pending_prompt=dashboard_state.get("pending_human_prompt"),
            last_launch_metadata=dashboard_state.get("last_applied_human_prompt"),
            title=DASHBOARD_TITLE,
        )
        encoded = html_text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_POST(self) -> None:  # pragma: no cover
        if self.path != "/api/prompt":
            self._write_json({"error": "not found"}, status=404)
            return
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        payload = json.loads(raw.decode("utf-8") or "{}")
        updated = queue_one_time_prompt(
            self.root,
            target=str(payload.get("target", "")),
            text=str(payload.get("text", "")),
            created_by="dashboard",
        )
        self._write_json(updated)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="sub-PHD dashboard for research automation observability.")
    ap.add_argument("--workdir", default=".")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--port-search-limit", type=int, default=20)
    ap.add_argument("--strict-port", action="store_true")
    ap.add_argument("--no-open-browser", action="store_true")
    return ap


def create_dashboard_server(
    host: str,
    port: int,
    *,
    port_search_limit: int = 20,
    strict_port: bool = False,
) -> ThreadingHTTPServer:
    if port == 0:
        return ThreadingHTTPServer((host, port), DashboardHandler)

    attempts = 1 if strict_port else max(1, port_search_limit)
    last_error: OSError | None = None
    for offset in range(attempts):
        candidate = port + offset
        try:
            return ThreadingHTTPServer((host, candidate), DashboardHandler)
        except OSError as exc:
            if exc.errno not in {errno.EADDRINUSE, errno.EACCES, 10048, 10013}:
                raise
            last_error = exc
            if strict_port:
                raise
    if last_error is not None:
        raise last_error
    raise RuntimeError("failed to create dashboard server")


def main() -> int:  # pragma: no cover
    args = build_parser().parse_args()
    root = Path(args.workdir).resolve()
    DashboardHandler.root = root
    server = create_dashboard_server(
        args.host,
        args.port,
        port_search_limit=args.port_search_limit,
        strict_port=args.strict_port,
    )
    actual_port = int(server.server_address[1])
    if args.port and actual_port != args.port:
        print(
            f"sub-PHD dashboard port {args.port} busy; fell back to http://{args.host}:{actual_port}/",
            flush=True,
        )
    if not args.no_open_browser:
        webbrowser.open(f"http://{args.host}:{actual_port}/")
    print(f"sub-PHD dashboard listening on http://{args.host}:{actual_port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
