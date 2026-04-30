import json
import os
import re
import time
from datetime import date, datetime
from decimal import Decimal
from urllib import error as url_error
from urllib import request as url_request

from flask import Blueprint, jsonify, render_template, request, session
from sqlalchemy import inspect, text

from app import db
from auth_utils import get_user_context
from models import AIAssistantQueryLog


ai_bp = Blueprint("ai", __name__)

_DEFAULT_GEMINI_MODEL = "gemini-1.5-pro"
_GEMINI_FALLBACK_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
]
_FORBIDDEN_SQL = (
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "truncate",
    "create",
    "replace",
    "grant",
    "revoke",
    "attach",
    "detach",
    "vacuum",
    "pragma",
)
_SENSITIVE_TABLES = {
    "user",
    "role",
    "permission",
    "role_permissions",
    "login_log",
    "activity_log",
    "activity_logs",
    "system_setting",
    "login_attempt",
    "device_fcm_token",
}
_DOMAIN_PACKS = {
    "fuel": "Fuel analytics focus: fuel_expense, vehicle, project, district. Prefer monthly totals, per-vehicle avg, and trend readiness.",
    "payroll": "Payroll analytics focus: monthly_payroll, employee_salary_config, employee, driver_attendance. Use net_pay, payable_days, payment_status when present.",
    "attendance": "Attendance analytics focus: driver_attendance, driver, vehicle, district. Include attendance_date, check_in/check_out gaps, late/missing checkout patterns.",
    "maintenance": "Maintenance analytics focus: maintenance_expense, maintenance_work_order, oil_expense, vehicle. Prefer cost by category, vehicle, and month.",
    "workspace": "Workspace finance focus: workspace_* tables, workspace_journal_entry, workspace_expense, workspace_fund_transfer, month close summaries.",
}


def _json_default(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _schema_context():
    insp = inspect(db.engine)
    lines = []
    for table_name in sorted(insp.get_table_names()):
        cols = insp.get_columns(table_name)
        pk_cols = set(insp.get_pk_constraint(table_name).get("constrained_columns") or [])
        fk_map = {}
        for fk in insp.get_foreign_keys(table_name):
            for constrained in fk.get("constrained_columns") or []:
                target_table = fk.get("referred_table") or ""
                target_cols = ",".join(fk.get("referred_columns") or [])
                fk_map[constrained] = f"{target_table}({target_cols})"

        lines.append(f"Table: {table_name}")
        for col in cols:
            name = col.get("name")
            col_type = str(col.get("type"))
            tags = []
            if name in pk_cols:
                tags.append("PK")
            if name in fk_map:
                tags.append(f"FK->{fk_map[name]}")
            tag_suffix = f" [{' | '.join(tags)}]" if tags else ""
            lines.append(f"  - {name}: {col_type}{tag_suffix}")
    return "\n".join(lines)


def _table_columns_map():
    insp = inspect(db.engine)
    out = {}
    for table_name in insp.get_table_names():
        out[table_name] = {c.get("name") for c in insp.get_columns(table_name)}
    return out


def _extract_sql(raw_text):
    if not raw_text:
        return ""
    text_value = raw_text.strip()
    fenced = re.search(r"```(?:sql)?\s*(.*?)```", text_value, re.IGNORECASE | re.DOTALL)
    if fenced:
        text_value = fenced.group(1).strip()
    if text_value.lower().startswith("sql"):
        text_value = text_value[3:].strip(": \n")
    return text_value.strip().rstrip(";")


def _extract_table_names(sql_query):
    if not sql_query:
        return set()
    lower = re.sub(r"\s+", " ", sql_query).lower()
    names = set()
    for pat in (r"\bfrom\s+([a-zA-Z_][\w\.]*)", r"\bjoin\s+([a-zA-Z_][\w\.]*)"):
        for m in re.finditer(pat, lower):
            tbl = (m.group(1) or "").split(".")[-1]
            tbl = tbl.strip().strip('"').strip("`")
            if tbl:
                names.add(tbl)
    return names


def _prompt_pack_for_question(question):
    q = (question or "").lower()
    picks = []
    for key, val in _DOMAIN_PACKS.items():
        if key in q:
            picks.append(val)
    if not picks:
        picks.append("General fleet analytics: prioritize aggregations and business-readable aliases.")
    return "\n".join(f"- {p}" for p in picks)


def _is_read_only_sql(query):
    if not query:
        return False
    compact = re.sub(r"\s+", " ", query).strip().lower()
    if not (compact.startswith("select ") or compact.startswith("with ")):
        return False
    if ";" in compact:
        return False
    for word in _FORBIDDEN_SQL:
        if re.search(rf"\b{re.escape(word)}\b", compact):
            return False
    return True


def _allow_tables_for_current_user(table_names):
    if not table_names:
        return True, ""
    if session.get("is_master"):
        return True, ""
    blocked = sorted([t for t in table_names if t in _SENSITIVE_TABLES])
    if blocked:
        return False, f"Sensitive table access blocked for current role: {', '.join(blocked)}"
    return True, ""


def _scope_policy_for_user():
    uid = session.get("user_id")
    ctx = get_user_context(uid) if uid else {}
    is_unrestricted = bool(session.get("is_master")) or bool(ctx.get("is_master_or_admin"))
    return {
        "is_unrestricted": is_unrestricted,
        "allowed_projects": set(ctx.get("allowed_projects") or []),
        "allowed_districts": set(ctx.get("allowed_districts") or []),
    }


def _scope_prompt_fragment(policy):
    if policy.get("is_unrestricted"):
        return "User has unrestricted scope (master/admin)."
    parts = []
    proj = sorted(policy.get("allowed_projects") or [])
    dist = sorted(policy.get("allowed_districts") or [])
    if proj:
        parts.append(f"Only allowed project_id values: {proj}.")
    if dist:
        parts.append(f"Only allowed district_id values: {dist}.")
    if not parts:
        parts.append("No explicit assignment found, keep query as safe read-only and minimal.")
    return " ".join(parts)


def _enforce_scope(sql_query, table_names, policy, table_columns):
    if policy.get("is_unrestricted"):
        return True, ""
    sql_l = (sql_query or "").lower()
    allowed_projects = policy.get("allowed_projects") or set()
    allowed_districts = policy.get("allowed_districts") or set()

    for table_name in table_names:
        cols = table_columns.get(table_name, set())
        if "project_id" in cols and allowed_projects and "project_id" not in sql_l:
            return False, "Scoped access: query must include project_id filter for your assigned projects."
        if "district_id" in cols and allowed_districts and "district_id" not in sql_l:
            return False, "Scoped access: query must include district_id filter for your assigned districts."
    return True, ""


def _log_query(question, sql_query, rows_count, status, error_message="", chart_requested=False, duration_ms=None):
    try:
        row = AIAssistantQueryLog(
            user_id=session.get("user_id"),
            question=question,
            sql_query=sql_query,
            rows_count=rows_count or 0,
            status=status,
            error_message=error_message[:3000] if error_message else None,
            chart_requested=bool(chart_requested),
            duration_ms=duration_ms,
        )
        db.session.add(row)
        db.session.commit()
    except Exception:
        db.session.rollback()


def _call_gemini(prompt, temperature=0.1):
    api_key = (os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY is missing in environment variables.")

    preferred = (os.environ.get("GEMINI_MODEL") or "").strip() or _DEFAULT_GEMINI_MODEL

    def _post_generate(model_name):
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
            f"?key={api_key}"
        )
        payload = {
            "generationConfig": {"temperature": temperature},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        }
        data = json.dumps(payload).encode("utf-8")
        req = url_request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        with url_request.urlopen(req, timeout=45) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _available_models():
        list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
        req = url_request.Request(list_url, method="GET")
        with url_request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        out = []
        for model in body.get("models") or []:
            name = (model.get("name") or "").strip()
            if not name:
                continue
            short_name = name.split("/", 1)[-1]  # models/gemini-2.0-flash -> gemini-2.0-flash
            methods = model.get("supportedGenerationMethods") or []
            if "generateContent" in methods:
                out.append(short_name)
        return out

    model_candidates = [preferred] + [m for m in _GEMINI_FALLBACK_MODELS if m != preferred]
    attempted = []

    for model_name in model_candidates:
        attempted.append(model_name)
        try:
            body = _post_generate(model_name)
            candidates = body.get("candidates") or []
            if not candidates:
                raise RuntimeError("Gemini did not return any candidate response.")
            parts = (((candidates[0] or {}).get("content") or {}).get("parts")) or []
            text_chunks = [p.get("text", "") for p in parts if isinstance(p, dict)]
            return "\n".join([t for t in text_chunks if t]).strip()
        except url_error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="ignore")
            # If model not found, continue to next fallback model.
            if exc.code == 404 and "not found" in err_body.lower():
                continue
            raise RuntimeError(f"Gemini HTTP {exc.code}: {err_body[:300]}") from exc
        except Exception as exc:
            # Network/runtime issues should fail fast.
            raise RuntimeError(f"Gemini request failed: {exc}") from exc

    # Last attempt: discover models dynamically and try first supported one.
    try:
        discovered = _available_models()
        for model_name in discovered:
            if model_name in attempted:
                continue
            try:
                body = _post_generate(model_name)
                candidates = body.get("candidates") or []
                if not candidates:
                    continue
                parts = (((candidates[0] or {}).get("content") or {}).get("parts")) or []
                text_chunks = [p.get("text", "") for p in parts if isinstance(p, dict)]
                answer = "\n".join([t for t in text_chunks if t]).strip()
                if answer:
                    return answer
            except Exception:
                continue
        raise RuntimeError(f"No compatible Gemini model available. Tried: {', '.join(attempted)}")
    except Exception as exc:
        raise RuntimeError(f"Gemini model resolution failed: {exc}") from exc


def _rows_to_dicts(result):
    return [dict(row._mapping) for row in result]


def _build_chart_data(rows, chart_hint):
    if not rows:
        return None

    chart_type = (chart_hint or {}).get("type") or "bar"
    x_key = (chart_hint or {}).get("x")
    y_key = (chart_hint or {}).get("y")
    first = rows[0]
    keys = list(first.keys())
    if len(keys) < 2:
        return None

    if not x_key or x_key not in first:
        x_key = keys[0]
    if not y_key or y_key not in first:
        numeric_keys = [k for k in keys if isinstance(first.get(k), (int, float, Decimal))]
        y_key = numeric_keys[0] if numeric_keys else keys[1]

    labels = [str(r.get(x_key, "")) for r in rows[:50]]
    values = []
    for row in rows[:50]:
        raw = row.get(y_key)
        if isinstance(raw, Decimal):
            raw = float(raw)
        if isinstance(raw, (int, float)):
            values.append(raw)
        else:
            try:
                values.append(float(raw))
            except Exception:
                values.append(0)

    return {
        "type": chart_type if chart_type in ("bar", "line", "pie") else "bar",
        "title": f"{y_key} by {x_key}",
        "labels": labels,
        "datasets": [{"label": y_key, "data": values}],
    }


@ai_bp.route("/ai-assistant")
def ai_assistant():
    return render_template("ai_assistant.html")


@ai_bp.route("/api/ai/query", methods=["POST"])
def ai_query():
    started_at = time.time()
    payload = request.get_json(silent=True) or {}
    user_question = (payload.get("message") or "").strip()
    if not user_question:
        return jsonify({"ok": False, "error": "Question is required."}), 400

    schema = _schema_context()
    policy = _scope_policy_for_user()
    scope_fragment = _scope_prompt_fragment(policy)
    domain_pack = _prompt_pack_for_question(user_question)
    sql_prompt = f"""
You are a FleetManager SQL analyst.
Return ONLY strict JSON (no markdown) with keys:
- sql: SQL SELECT query only
- chart: object {{ requested: bool, type: "bar"|"line"|"pie", x: "<column>", y: "<column>" }}
- next_steps: array of max 3 objects {{ label: "...", url: "..." }} with practical links if relevant

Rules:
1) SQL must be READ-ONLY. Only SELECT or WITH...SELECT.
2) Never use INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE/CREATE.
3) Keep query compatible with SQLite/PostgreSQL basics.
4) Prefer aliases in English for aggregated columns.
5) If user asks for month/date logic, infer best effort with current DB fields.
6) Keep output safe and analytics-oriented.
7) Respect user data scope strictly.

Domain guidance:
{domain_pack}

User scope constraints:
{scope_fragment}

User question:
{user_question}

Database schema:
{schema}
"""
    try:
        llm_raw = _call_gemini(sql_prompt, temperature=0.05)
        parsed = json.loads(llm_raw)
    except Exception as exc:
        _log_query(user_question, "", 0, "error", f"SQL generation failed: {exc}", False, int((time.time() - started_at) * 1000))
        return jsonify({"ok": False, "error": f"Failed to generate SQL: {exc}"}), 500

    sql_query = _extract_sql((parsed or {}).get("sql", ""))
    if not _is_read_only_sql(sql_query):
        _log_query(
            user_question,
            sql_query,
            0,
            "blocked",
            "Non read-only SQL blocked.",
            bool((parsed or {}).get("chart", {}).get("requested")),
            int((time.time() - started_at) * 1000),
        )
        return jsonify(
            {
                "ok": False,
                "error": "Generated query was not read-only. Please rephrase your question.",
            }
        ), 400

    table_names = _extract_table_names(sql_query)
    allowed, reason = _allow_tables_for_current_user(table_names)
    if not allowed:
        _log_query(
            user_question,
            sql_query,
            0,
            "blocked",
            reason,
            bool((parsed or {}).get("chart", {}).get("requested")),
            int((time.time() - started_at) * 1000),
        )
        return jsonify({"ok": False, "error": reason}), 403

    table_columns = _table_columns_map()
    scope_ok, scope_reason = _enforce_scope(sql_query, table_names, policy, table_columns)
    if not scope_ok:
        _log_query(
            user_question,
            sql_query,
            0,
            "blocked",
            scope_reason,
            bool((parsed or {}).get("chart", {}).get("requested")),
            int((time.time() - started_at) * 1000),
        )
        return jsonify({"ok": False, "error": scope_reason}), 403

    safe_sql = f"SELECT * FROM ({sql_query}) AS ai_q LIMIT 500"
    try:
        result = db.session.execute(text(safe_sql))
        rows = _rows_to_dicts(result)
    except Exception as exc:
        _log_query(
            user_question,
            sql_query,
            0,
            "error",
            f"SQL execution failed: {exc}",
            bool((parsed or {}).get("chart", {}).get("requested")),
            int((time.time() - started_at) * 1000),
        )
        return jsonify({"ok": False, "error": f"SQL execution failed: {exc}", "sql": sql_query}), 400

    explain_prompt = f"""
You are FleetManager Master Mind AI.
Explain result in concise Roman Urdu + English mix.
Keep response actionable and business-focused.
If data is empty, clearly say no record found.

Question: {user_question}
SQL: {sql_query}
Result rows JSON: {json.dumps(rows[:80], default=_json_default)}
Total rows fetched: {len(rows)}
"""
    try:
        answer_text = _call_gemini(explain_prompt, temperature=0.2)
    except Exception as exc:
        answer_text = f"Data mil gaya, lekin AI explanation abhi unavailable hai ({exc})."

    chart_hint = (parsed or {}).get("chart") or {}
    wants_chart = bool(chart_hint.get("requested")) or any(
        kw in user_question.lower() for kw in ("chart", "graph", "plot", "trend", "bar", "line", "pie")
    )
    chart_data = _build_chart_data(rows, chart_hint) if wants_chart else None

    next_steps = (parsed or {}).get("next_steps") or []
    if not isinstance(next_steps, list):
        next_steps = []
    next_steps = [s for s in next_steps if isinstance(s, dict) and s.get("label") and s.get("url")][:3]

    elapsed_ms = int((time.time() - started_at) * 1000)
    _log_query(user_question, sql_query, len(rows), "success", "", wants_chart, elapsed_ms)

    return jsonify(
        {
            "ok": True,
            "answer": answer_text,
            "sql": sql_query,
            "rows_count": len(rows),
            "preview_rows": rows[:25],
            "chart_data": chart_data,
            "next_steps": next_steps,
            "duration_ms": elapsed_ms,
        }
    )


@ai_bp.route("/api/ai/recent", methods=["GET"])
def ai_recent():
    limit = min(max(int(request.args.get("limit", 10)), 1), 50)
    q = AIAssistantQueryLog.query.order_by(AIAssistantQueryLog.created_at.desc())
    if not session.get("is_master"):
        q = q.filter(AIAssistantQueryLog.user_id == session.get("user_id"))
    rows = q.limit(limit).all()
    out = [
        {
            "id": r.id,
            "question": (r.question or "")[:120],
            "status": r.status,
            "rows_count": r.rows_count,
            "created_at": r.created_at.isoformat() if r.created_at else "",
            "duration_ms": r.duration_ms,
        }
        for r in rows
    ]
    return jsonify({"ok": True, "items": out})

