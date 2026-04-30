import json
import os
import re
import time
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from urllib.parse import urlparse
from urllib import error as url_error
from urllib import request as url_request

from flask import Blueprint, current_app, jsonify, render_template, request, session
from sqlalchemy import inspect, text
from werkzeug.exceptions import HTTPException

from app import csrf, db
from auth_utils import get_required_permission, get_user_context, user_can_access
from models import AIAssistantQueryLog, AIConversation, AIConversationMessage


ai_bp = Blueprint("ai", __name__)
_AI_SCHEMA_CHECKED = False

_DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
_GEMINI_FALLBACK_MODELS = [
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
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
_TABLE_BUSINESS_HINTS = {
    "fuel_expense": "Fuel costs with date, amount, vehicle/project links.",
    "vehicle": "Vehicle master (registration, model, assignment fields).",
    "driver_attendance": "Daily driver attendance and check-in/out pattern.",
    "monthly_payroll": "Monthly payroll aggregates (salary/payable/payment status).",
    "workspace_expense": "Workspace operational expenses by account/category/date.",
    "district": "Geographic/administrative location dimension.",
    "project": "Project/client/site dimension used for scoping.",
}
_SQL_FEW_SHOTS = """
Example 1
Question: "Last 6 months fuel trend by month"
SQL:
SELECT strftime('%Y-%m', fe.expense_date) AS month, SUM(fe.amount) AS total_fuel_amount
FROM fuel_expense fe
GROUP BY strftime('%Y-%m', fe.expense_date)
ORDER BY month DESC
LIMIT 6

Example 2
Question: "Top 10 vehicles by maintenance spend"
SQL:
SELECT v.registration_no AS vehicle, SUM(me.amount) AS maintenance_total
FROM maintenance_expense me
JOIN vehicle v ON v.id = me.vehicle_id
GROUP BY v.registration_no
ORDER BY maintenance_total DESC
LIMIT 10
"""
_RATE_WINDOW_SECONDS = int((os.environ.get("AI_RATE_WINDOW_SECONDS") or "300").strip() or "300")
_RATE_LIMIT_PER_WINDOW = int((os.environ.get("AI_RATE_LIMIT_PER_WINDOW") or "25").strip() or "25")
_GEMINI_RETRYABLE_HTTP_CODES = {500, 503, 504}
_GEMINI_HTTP_TIMEOUT_SECONDS = float((os.environ.get("AI_GEMINI_HTTP_TIMEOUT_SECONDS") or "20").strip() or "20")
_GEMINI_TOTAL_BUDGET_SECONDS = float((os.environ.get("AI_GEMINI_TOTAL_BUDGET_SECONDS") or "28").strip() or "28")
_GEMINI_MAX_DISCOVERED_ATTEMPTS = int((os.environ.get("AI_GEMINI_MAX_DISCOVERED_ATTEMPTS") or "2").strip() or "2")


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


def _ensure_ai_conversation_schema():
    global _AI_SCHEMA_CHECKED
    if _AI_SCHEMA_CHECKED:
        return True, ""
    try:
        required = {"is_pinned", "summary_text", "pinned_facts_json", "instruction_policy_json"}
        bind = None
        try:
            bind = db.session.get_bind()
        except Exception:
            bind = None
        if bind is None:
            bind = db.engine
        dialect = (((bind.dialect.name if bind is not None else "") or "").lower())
        for _ in range(2):
            insp = inspect(db.engine)
            if "ai_conversation" not in insp.get_table_names():
                _AI_SCHEMA_CHECKED = True
                return True, ""
            existing = {c.get("name") for c in insp.get_columns("ai_conversation")}
            missing = [c for c in required if c not in existing]
            if not missing:
                _AI_SCHEMA_CHECKED = True
                return True, ""
            ddl_list = []
            for col in missing:
                if col == "is_pinned":
                    if dialect == "postgresql":
                        ddl_list.append("ALTER TABLE ai_conversation ADD COLUMN IF NOT EXISTS is_pinned BOOLEAN NOT NULL DEFAULT FALSE")
                    else:
                        ddl_list.append("ALTER TABLE ai_conversation ADD COLUMN is_pinned BOOLEAN NOT NULL DEFAULT FALSE")
                elif col == "summary_text":
                    if dialect == "postgresql":
                        ddl_list.append("ALTER TABLE ai_conversation ADD COLUMN IF NOT EXISTS summary_text TEXT")
                    else:
                        ddl_list.append("ALTER TABLE ai_conversation ADD COLUMN summary_text TEXT")
                elif col == "pinned_facts_json":
                    if dialect == "postgresql":
                        ddl_list.append("ALTER TABLE ai_conversation ADD COLUMN IF NOT EXISTS pinned_facts_json TEXT")
                    else:
                        ddl_list.append("ALTER TABLE ai_conversation ADD COLUMN pinned_facts_json TEXT")
                elif col == "instruction_policy_json":
                    if dialect == "postgresql":
                        ddl_list.append("ALTER TABLE ai_conversation ADD COLUMN IF NOT EXISTS instruction_policy_json TEXT")
                    else:
                        ddl_list.append("ALTER TABLE ai_conversation ADD COLUMN instruction_policy_json TEXT")
            for ddl in ddl_list:
                db.session.execute(text(ddl))
            db.session.commit()
        return False, "AI schema mismatch: missing required ai_conversation columns."
    except Exception as exc:
        db.session.rollback()
        return False, f"AI schema migration failed: {exc}"


def _schema_dictionary_text():
    insp = inspect(db.engine)
    lines = []
    for table_name in sorted(insp.get_table_names()):
        hint = _TABLE_BUSINESS_HINTS.get(table_name)
        if hint:
            lines.append(f"- {table_name}: {hint}")
    return "\n".join(lines) if lines else "- No table hints configured."


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


def _rewrite_to_readonly_sql(user_question, raw_sql, schema_text):
    fixer_prompt = f"""
Rewrite the SQL below into a STRICT READ-ONLY query.
Return JSON only: {{"sql":"<query>"}}

Rules:
1) Only SELECT or WITH...SELECT.
2) Never use INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE/CREATE/REPLACE.
3) Keep SQL compatible with SQLite/PostgreSQL basics.
4) Keep user intent unchanged.
5) Do not include markdown.

User question:
{user_question}

Original SQL:
{raw_sql}

Database schema:
{schema_text}
"""
    fixed_raw = _call_gemini(fixer_prompt, temperature=0.0)
    fixed_json = _parse_llm_json(fixed_raw)
    return _extract_sql((fixed_json or {}).get("sql", ""))


def _parse_llm_json(raw_text):
    text_value = (raw_text or "").strip()
    if not text_value:
        raise ValueError("LLM returned empty response.")
    try:
        return json.loads(text_value)
    except Exception:
        pass

    fenced = re.search(r"```(?:json)?\s*(.*?)```", text_value, re.IGNORECASE | re.DOTALL)
    if fenced:
        inner = fenced.group(1).strip()
        if inner:
            try:
                return json.loads(inner)
            except Exception:
                pass

    obj_match = re.search(r"\{.*\}", text_value, re.DOTALL)
    if obj_match:
        maybe_json = obj_match.group(0).strip()
        if maybe_json:
            return json.loads(maybe_json)

    raise ValueError("Could not parse JSON from LLM response.")


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


def _rate_limit_guard(user_id):
    if not user_id:
        return True, ""
    ctx = get_user_context(user_id) if user_id else {}
    is_admin_or_master = bool(session.get("is_master")) or bool(ctx.get("is_master_or_admin"))
    if is_admin_or_master:
        return True, ""
    since_epoch = int(time.time()) - _RATE_WINDOW_SECONDS
    since_dt = datetime.utcfromtimestamp(since_epoch)
    cnt = (
        AIAssistantQueryLog.query
        .filter(AIAssistantQueryLog.user_id == user_id)
        .filter(AIAssistantQueryLog.created_at >= since_dt)
        .count()
    )
    if cnt >= _RATE_LIMIT_PER_WINDOW:
        return False, f"Rate limit exceeded: {_RATE_LIMIT_PER_WINDOW} requests in {_RATE_WINDOW_SECONDS // 60} minutes."
    return True, ""


def _preflight_validate_sql(sql_query):
    q = (sql_query or "").strip().lower()
    if not q:
        return False, "Generated SQL is empty."
    if re.search(r"\blimit\s+([0-9]+)\b", q):
        try:
            lim = int(re.search(r"\blimit\s+([0-9]+)\b", q).group(1))
            if lim > 2000:
                return False, "SQL limit too high (max 2000)."
        except Exception:
            pass
    if "select *" in q:
        return False, "Avoid SELECT * for safety/performance. Please ask focused columns."
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


def _get_or_create_conversation(user_id, conversation_id, first_question):
    conv = None
    if conversation_id:
        conv = AIConversation.query.filter_by(id=conversation_id, user_id=user_id).first()
    if not conv:
        title = (first_question or "New AI Chat").strip()[:220] or "New AI Chat"
        conv = AIConversation(user_id=user_id, title=title)
        db.session.add(conv)
        db.session.flush()
    return conv


def _add_conversation_message(conversation, role, content, sql_query=None, chart_data=None):
    msg = AIConversationMessage(
        conversation_id=conversation.id,
        role=role,
        content=content or "",
        sql_query=sql_query,
        chart_json=json.dumps(chart_data, default=_json_default) if chart_data else None,
    )
    db.session.add(msg)
    conversation.updated_at = datetime.utcnow()


def _refresh_conversation_memory(conversation):
    msgs = (
        AIConversationMessage.query
        .filter_by(conversation_id=conversation.id)
        .order_by(AIConversationMessage.created_at.asc())
        .all()
    )
    if not msgs:
        conversation.summary_text = None
        conversation.pinned_facts_json = None
        conversation.instruction_policy_json = None
        return

    # 1) Compressed summary for long chats (older turns only)
    recent_cut = 10
    older = msgs[:-recent_cut] if len(msgs) > recent_cut else []
    summary_lines = []
    char_budget = 2200
    used = 0
    for m in older[-12:]:
        role_tag = "U" if m.role == "user" else "A"
        chunk = (m.content or "").replace("\n", " ").strip()
        if not chunk:
            continue
        chunk = (chunk[:180] + "...") if len(chunk) > 180 else chunk
        line = f"{role_tag}: {chunk}"
        if used + len(line) > char_budget:
            break
        summary_lines.append(line)
        used += len(line)
    conversation.summary_text = "\n".join(summary_lines) if summary_lines else None

    # 2) Pinned key facts (constraints/instructions)
    fact_keywords = ("must", "only", "never", "always", "required", "constraint", "scope", "project", "district", "read-only")
    facts = []
    seen = set()
    for m in msgs:
        if m.role != "user":
            continue
        text_val = (m.content or "").strip()
        if not text_val:
            continue
        sentences = re.split(r"[.\n!?]+", text_val)
        for s in sentences:
            s = s.strip()
            if len(s) < 8:
                continue
            low = s.lower()
            if any(k in low for k in fact_keywords):
                norm = low[:140]
                if norm in seen:
                    continue
                seen.add(norm)
                facts.append(s[:180])
            if len(facts) >= 10:
                break
        if len(facts) >= 10:
            break
    conversation.pinned_facts_json = json.dumps(facts, ensure_ascii=True) if facts else None

    # 3) Explicit instruction priority policy (latest instruction override + constraints preservation)
    latest_user = ""
    for m in reversed(msgs):
        if m.role == "user" and (m.content or "").strip():
            latest_user = (m.content or "").strip()[:260]
            break
    policy = {
        "priority_order": [
            "Hard security constraints (READ-ONLY SQL + scope restrictions)",
            "Latest user instruction in current conversation",
            "Pinned key facts from conversation memory",
            "Older context summary"
        ],
        "latest_user_instruction": latest_user,
        "preserve_constraints": [
            "Never run write SQL",
            "Respect project/district scope guards",
            "Keep result actionable and concise"
        ]
    }
    conversation.instruction_policy_json = json.dumps(policy, ensure_ascii=True)


def _build_conversation_context(conversation_id, max_messages=12, max_chars=4500):
    if not conversation_id:
        return ""
    conv = AIConversation.query.get(conversation_id)
    if not conv:
        return ""
    rows = (
        AIConversationMessage.query
        .filter_by(conversation_id=conversation_id)
        .order_by(AIConversationMessage.created_at.desc())
        .limit(max_messages)
        .all()
    )
    if not rows:
        return ""
    rows = list(reversed(rows))
    parts = []
    used = 0
    for r in rows:
        role = "User" if r.role == "user" else "Assistant"
        text_part = (r.content or "").strip()
        if not text_part:
            continue
        chunk = f"{role}: {text_part}"
        if r.sql_query and r.role == "assistant":
            chunk += f"\nAssistant SQL: {r.sql_query}"
        if used + len(chunk) > max_chars:
            break
        parts.append(chunk)
        used += len(chunk)

    blocks = []
    if conv.summary_text:
        blocks.append("Conversation Summary (older turns):\n" + conv.summary_text)
    if conv.pinned_facts_json:
        try:
            facts = json.loads(conv.pinned_facts_json) or []
        except Exception:
            facts = []
        if facts:
            fact_lines = "\n".join(["- " + str(f) for f in facts[:8]])
            blocks.append("Pinned Key Facts:\n" + fact_lines)
    if conv.instruction_policy_json:
        try:
            pol = json.loads(conv.instruction_policy_json) or {}
        except Exception:
            pol = {}
        if pol:
            blocks.append("Instruction Priority Policy:\n" + json.dumps(pol, ensure_ascii=False))
    if parts:
        blocks.append("Recent Conversation Turns:\n" + "\n\n".join(parts))
    return "\n\n".join(blocks)


def _call_gemini(prompt, temperature=0.1):
    api_key = (os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY is missing in environment variables.")

    preferred = (os.environ.get("GEMINI_MODEL") or "").strip() or _DEFAULT_GEMINI_MODEL
    deadline = time.monotonic() + max(3.0, _GEMINI_TOTAL_BUDGET_SECONDS)

    def _remaining_seconds():
        return max(0.0, deadline - time.monotonic())

    def _is_quota_error(message):
        txt = (message or "").lower()
        return ("http 429" in txt) or ("quota" in txt) or ("rate limit" in txt) or ("resource_exhausted" in txt)

    def _post_generate(model_name):
        remaining = _remaining_seconds()
        if remaining <= 0.2:
            raise RuntimeError("Gemini request budget exhausted before API call.")
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
        req_timeout = max(1.0, min(_GEMINI_HTTP_TIMEOUT_SECONDS, remaining))
        with url_request.urlopen(req, timeout=req_timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _call_model_with_retries(model_name, retries=2):
        wait_seconds = 0.8
        last_exc = None
        for attempt in range(retries + 1):
            if _remaining_seconds() <= 0.2:
                break
            try:
                return _post_generate(model_name)
            except url_error.HTTPError as exc:
                err_body = exc.read().decode("utf-8", errors="ignore")
                if exc.code in _GEMINI_RETRYABLE_HTTP_CODES and attempt < retries:
                    time.sleep(wait_seconds)
                    wait_seconds = min(wait_seconds * 1.8, 3.0)
                    last_exc = RuntimeError(f"Gemini transient HTTP {exc.code}: {err_body[:220]}")
                    continue
                raise RuntimeError(f"Gemini HTTP {exc.code}: {err_body[:300]}") from exc
            except Exception as exc:
                if attempt < retries:
                    time.sleep(wait_seconds)
                    wait_seconds = min(wait_seconds * 1.8, 3.0)
                    last_exc = RuntimeError(f"Gemini request transient failure: {exc}")
                    continue
                raise RuntimeError(f"Gemini request failed: {exc}") from exc
        if last_exc:
            raise last_exc
        raise RuntimeError(f"Gemini request budget exhausted while trying model: {model_name}")

    def _available_models():
        remaining = _remaining_seconds()
        if remaining <= 0.2:
            return []
        list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
        req = url_request.Request(list_url, method="GET")
        with url_request.urlopen(req, timeout=max(1.0, min(_GEMINI_HTTP_TIMEOUT_SECONDS, remaining))) as resp:
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
    last_error_message = ""

    for model_name in model_candidates:
        attempted.append(model_name)
        try:
            body = _call_model_with_retries(model_name)
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
            msg = str(exc)
            last_error_message = msg[:600]
            if _is_quota_error(msg):
                raise RuntimeError(f"Gemini quota/rate-limit error: {msg}") from exc
            # Auth/config problems should fail fast with real reason.
            if ("HTTP 401" in msg) or ("HTTP 403" in msg) or ("API key" in msg.lower()):
                raise RuntimeError(f"Gemini authentication/config error: {msg}") from exc
            # Otherwise continue trying fallback models.
            continue

    # Last attempt: discover a few models dynamically (bounded for latency).
    try:
        discovered = _available_models()
        discovered = [m for m in discovered if "gemini" in m.lower()]
        discovered = [m for m in discovered if m not in attempted]
        discovered = discovered[:max(0, _GEMINI_MAX_DISCOVERED_ATTEMPTS)]
        for model_name in discovered:
            if _remaining_seconds() <= 0.2:
                break
            try:
                body = _call_model_with_retries(model_name)
                candidates = body.get("candidates") or []
                if not candidates:
                    continue
                parts = (((candidates[0] or {}).get("content") or {}).get("parts")) or []
                text_chunks = [p.get("text", "") for p in parts if isinstance(p, dict)]
                answer = "\n".join([t for t in text_chunks if t]).strip()
                if answer:
                    return answer
            except Exception as exc:
                last_error_message = str(exc)[:600]
                continue
        tail = f" Last error: {last_error_message}" if last_error_message else ""
        raise RuntimeError(f"No compatible Gemini model available. Tried: {', '.join(attempted)}.{tail}")
    except Exception as exc:
        raise RuntimeError(f"Gemini model resolution failed: {exc}") from exc


def _rows_to_dicts(result):
    return [dict(row._mapping) for row in result]


@ai_bp.errorhandler(Exception)
def _ai_error_handler(exc):
    if isinstance(exc, HTTPException):
        return exc
    if (request.path or "").startswith("/api/ai/"):
        try:
            db.session.rollback()
        except Exception:
            pass
        return jsonify({"ok": False, "error": f"AI API internal error: {exc}"}), 500
    raise exc


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


def _is_valid_internal_get_url(url_value):
    if not url_value:
        return False
    parsed = urlparse(str(url_value).strip())
    if parsed.scheme or parsed.netloc:
        return False
    path = parsed.path or ""
    if not path.startswith("/"):
        return False
    try:
        adapter = current_app.url_map.bind("")
        adapter.match(path, method="GET")
        return True
    except Exception:
        return False


def _sanitize_next_steps(raw_steps):
    if not isinstance(raw_steps, list):
        return []
    out = []
    for step in raw_steps:
        if not isinstance(step, dict):
            continue
        label = str(step.get("label") or "").strip()[:90]
        url = str(step.get("url") or "").strip()
        if not label or not _is_valid_internal_get_url(url):
            continue
        out.append({"label": label, "url": url})
        if len(out) >= 3:
            break
    return out


@ai_bp.route("/ai-assistant")
def ai_assistant():
    return render_template("ai_assistant.html")


@ai_bp.route("/api/ai/query", methods=["POST"])
@csrf.exempt
def ai_query():
    ok_schema, schema_err = _ensure_ai_conversation_schema()
    if not ok_schema:
        return jsonify({"ok": False, "error": schema_err}), 500
    started_at = time.time()
    payload = request.get_json(silent=True) or {}
    user_question = (payload.get("message") or "").strip()
    conversation_id = payload.get("conversation_id")
    uid = session.get("user_id")
    if not user_question:
        return jsonify({"ok": False, "error": "Question is required."}), 400

    if not uid:
        return jsonify({"ok": False, "error": "Session expired. Please login again."}), 401
    if len(user_question) > 2000:
        return jsonify({"ok": False, "error": "Question too long. Keep it under 2000 characters."}), 400
    if not session.get("is_master"):
        ok_rate, rate_reason = _rate_limit_guard(uid)
        if not ok_rate:
            return jsonify({"ok": False, "error": rate_reason}), 429

    conversation = _get_or_create_conversation(uid, conversation_id, user_question)
    _add_conversation_message(conversation, "user", user_question)
    _refresh_conversation_memory(conversation)
    db.session.commit()
    conv_context = _build_conversation_context(conversation.id)

    schema = _schema_context()
    policy = _scope_policy_for_user()
    scope_fragment = _scope_prompt_fragment(policy)
    domain_pack = _prompt_pack_for_question(user_question)
    schema_dictionary = _schema_dictionary_text()
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
8) Instruction precedence:
   - First: security constraints and scope.
   - Second: latest user instruction in this conversation.
   - Third: preserve pinned key facts from memory.
   - Fourth: use older summary only as fallback context.
9) Keep query efficient: avoid SELECT *, avoid unnecessary wide joins, and keep LIMIT sensible.

Domain guidance:
{domain_pack}

Business data dictionary:
{schema_dictionary}

Few-shot SQL patterns:
{_SQL_FEW_SHOTS}

User scope constraints:
{scope_fragment}

Conversation context (latest turns, use this to keep continuity):
{conv_context}

User question:
{user_question}

Database schema:
{schema}
"""
    try:
        # Lightweight routing: complex aggregation/join requests get higher-quality model.
        complex_need = any(k in user_question.lower() for k in ("join", "trend", "forecast", "compare", "breakdown", "correlation"))
        llm_raw = _call_gemini(sql_prompt, temperature=0.05 if complex_need else 0.02)
        parsed = _parse_llm_json(llm_raw)
    except Exception as exc:
        err_text = str(exc or "")
        err_lower = err_text.lower()
        if ("quota" in err_lower) or ("http 429" in err_lower) or ("rate-limit" in err_lower) or ("rate limit" in err_lower):
            quota_msg = (
                "AI service quota reached (Google Gemini 429). "
                "Please retry after 1-2 minutes or update billing/quota for GOOGLE_API_KEY."
            )
            _log_query(
                user_question,
                "",
                0,
                "error",
                f"{quota_msg} Raw: {err_text}",
                False,
                int((time.time() - started_at) * 1000),
            )
            _add_conversation_message(conversation, "assistant", quota_msg)
            _refresh_conversation_memory(conversation)
            db.session.commit()
            return jsonify({"ok": False, "error": quota_msg}), 429
        # One recovery attempt: ask model to normalize output into strict JSON.
        try:
            fixer_prompt = f"""
Convert the following content into strict JSON object with keys:
sql, chart, next_steps
Return JSON only.

Content:
{llm_raw if 'llm_raw' in locals() else ''}
"""
            llm_fixed = _call_gemini(fixer_prompt, temperature=0.0)
            parsed = _parse_llm_json(llm_fixed)
        except Exception as inner_exc:
            _log_query(
                user_question,
                "",
                0,
                "error",
                f"SQL generation failed: {exc}; normalize failed: {inner_exc}",
                False,
                int((time.time() - started_at) * 1000),
            )
            _add_conversation_message(conversation, "assistant", f"Failed to generate SQL: {inner_exc}")
            _refresh_conversation_memory(conversation)
            db.session.commit()
            return jsonify({"ok": False, "error": f"Failed to generate SQL: {inner_exc}"}), 500

    sql_query = _extract_sql((parsed or {}).get("sql", ""))
    if not _is_read_only_sql(sql_query):
        try:
            rewritten_sql = _rewrite_to_readonly_sql(user_question, sql_query, schema)
            if _is_read_only_sql(rewritten_sql):
                sql_query = rewritten_sql
        except Exception:
            pass
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
        _add_conversation_message(conversation, "assistant", "Generated query was blocked because it was not read-only.")
        _refresh_conversation_memory(conversation)
        db.session.commit()
        return jsonify(
            {
                "ok": False,
                "error": "Generated query was not read-only. Please rephrase your question.",
            }
        ), 400
    preflight_ok, preflight_reason = _preflight_validate_sql(sql_query)
    if not preflight_ok:
        _log_query(
            user_question,
            sql_query,
            0,
            "blocked",
            preflight_reason,
            bool((parsed or {}).get("chart", {}).get("requested")),
            int((time.time() - started_at) * 1000),
        )
        _add_conversation_message(conversation, "assistant", preflight_reason)
        _refresh_conversation_memory(conversation)
        db.session.commit()
        return jsonify({"ok": False, "error": preflight_reason}), 400

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
        _add_conversation_message(conversation, "assistant", reason)
        _refresh_conversation_memory(conversation)
        db.session.commit()
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
        _add_conversation_message(conversation, "assistant", scope_reason)
        _refresh_conversation_memory(conversation)
        db.session.commit()
        return jsonify({"ok": False, "error": scope_reason}), 403

    safe_sql = f"SELECT * FROM ({sql_query}) AS ai_q LIMIT 500"
    try:
        db.session.execute(text("EXPLAIN " + sql_query))
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
        _add_conversation_message(conversation, "assistant", f"SQL execution failed: {exc}", sql_query=sql_query)
        _refresh_conversation_memory(conversation)
        db.session.commit()
        return jsonify({"ok": False, "error": f"SQL execution failed: {exc}", "sql": sql_query}), 400

    explain_prompt = f"""
You are FleetManager Master Mind AI.
Explain result in concise Roman Urdu + English mix.
Keep response actionable and business-focused.
If data is empty, clearly say no record found.

Question: {user_question}
Conversation context:
{conv_context}
SQL: {sql_query}
Result rows JSON: {json.dumps(rows[:80], default=_json_default)}
Total rows fetched: {len(rows)}
"""
    try:
        answer_text = _call_gemini(explain_prompt, temperature=0.2)
    except Exception:
        answer_text = (
            "Data mil gaya, lekin AI explanation service temporary busy hai. "
            "Please 10-20 seconds baad dubara try karein."
        )

    chart_hint = (parsed or {}).get("chart") or {}
    wants_chart = bool(chart_hint.get("requested")) or any(
        kw in user_question.lower() for kw in ("chart", "graph", "plot", "trend", "bar", "line", "pie")
    )
    chart_data = _build_chart_data(rows, chart_hint) if wants_chart else None

    next_steps = _sanitize_next_steps((parsed or {}).get("next_steps") or [])

    elapsed_ms = int((time.time() - started_at) * 1000)
    _log_query(user_question, sql_query, len(rows), "success", "", wants_chart, elapsed_ms)
    _add_conversation_message(conversation, "assistant", answer_text, sql_query=sql_query, chart_data=chart_data)
    _refresh_conversation_memory(conversation)
    db.session.commit()

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
            "conversation_id": conversation.id,
        }
    )


@ai_bp.route("/api/ai/quality-score", methods=["GET"])
def ai_quality_score():
    uid = session.get("user_id")
    if not uid:
        return jsonify({"ok": False, "error": "Session expired."}), 401
    q = AIAssistantQueryLog.query
    if not session.get("is_master"):
        q = q.filter(AIAssistantQueryLog.user_id == uid)
    rows = q.order_by(AIAssistantQueryLog.created_at.desc()).limit(300).all()
    if not rows:
        return jsonify({"ok": True, "score_percent": 0, "sample_size": 0, "breakdown": {}})

    status_counts = defaultdict(int)
    durations = []
    chart_hits = 0
    for r in rows:
        status_counts[r.status or "unknown"] += 1
        if isinstance(r.duration_ms, int):
            durations.append(r.duration_ms)
        if r.chart_requested:
            chart_hits += 1

    total = len(rows)
    success_rate = (status_counts.get("success", 0) / total) * 100.0
    blocked_rate = (status_counts.get("blocked", 0) / total) * 100.0
    avg_latency = (sum(durations) / len(durations)) if durations else 0
    latency_score = 100 if avg_latency <= 3000 else max(20, 100 - ((avg_latency - 3000) / 120))
    chart_score = min(100, (chart_hits / total) * 180)  # 55%+ chart usage reaches 100

    final_score = round((success_rate * 0.55) + (latency_score * 0.25) + (chart_score * 0.20) - (blocked_rate * 0.10), 1)
    final_score = max(0, min(100, final_score))
    return jsonify(
        {
            "ok": True,
            "score_percent": final_score,
            "sample_size": total,
            "breakdown": {
                "success_rate_percent": round(success_rate, 1),
                "blocked_rate_percent": round(blocked_rate, 1),
                "avg_latency_ms": int(avg_latency),
                "chart_response_ratio_percent": round((chart_hits / total) * 100.0, 1),
            },
        }
    )


@ai_bp.route("/api/ai/debug-status", methods=["GET"])
def ai_debug_status():
    uid = session.get("user_id")
    endpoint = request.endpoint or "ai.ai_debug_status"
    required = get_required_permission(endpoint)
    perms = session.get("permissions") or []
    has_access = True if session.get("is_master") else user_can_access(perms, required)
    return jsonify(
        {
            "ok": True,
            "debug": {
                "path": request.path,
                "method": request.method,
                "endpoint": endpoint,
                "logged_in": bool(session.get("user")),
                "user_id": uid,
                "is_master": bool(session.get("is_master")),
                "required_permission": required,
                "has_permission": bool(has_access),
            },
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


@ai_bp.route("/api/ai/conversations", methods=["GET"])
def ai_conversations():
    ok_schema, schema_err = _ensure_ai_conversation_schema()
    if not ok_schema:
        return jsonify({"ok": False, "error": schema_err}), 500
    uid = session.get("user_id")
    if not uid:
        return jsonify({"ok": False, "error": "Session expired."}), 401
    rows = (
        AIConversation.query
        .filter_by(user_id=uid)
        .order_by(AIConversation.is_pinned.desc(), AIConversation.updated_at.desc())
        .limit(200)
        .all()
    )
    items = [
        {
            "id": r.id,
            "title": r.title,
            "is_pinned": bool(r.is_pinned),
            "created_at": r.created_at.isoformat() if r.created_at else "",
            "updated_at": r.updated_at.isoformat() if r.updated_at else "",
            "message_count": len(r.messages or []),
        }
        for r in rows
    ]
    return jsonify({"ok": True, "items": items})


@ai_bp.route("/api/ai/conversations/new", methods=["POST"])
@csrf.exempt
def ai_conversation_new():
    ok_schema, schema_err = _ensure_ai_conversation_schema()
    if not ok_schema:
        return jsonify({"ok": False, "error": schema_err}), 500
    uid = session.get("user_id")
    if not uid:
        return jsonify({"ok": False, "error": "Session expired."}), 401
    payload = request.get_json(silent=True) or {}
    title = ((payload.get("title") or "New AI Chat").strip()[:220]) or "New AI Chat"
    conv = AIConversation(user_id=uid, title=title)
    db.session.add(conv)
    db.session.commit()
    return jsonify({"ok": True, "id": conv.id})


@ai_bp.route("/api/ai/conversations/<int:conversation_id>", methods=["GET", "PATCH", "DELETE"])
@csrf.exempt
def ai_conversation_detail(conversation_id):
    ok_schema, schema_err = _ensure_ai_conversation_schema()
    if not ok_schema:
        return jsonify({"ok": False, "error": schema_err}), 500
    uid = session.get("user_id")
    if not uid:
        return jsonify({"ok": False, "error": "Session expired."}), 401
    conv = AIConversation.query.filter_by(id=conversation_id, user_id=uid).first()
    if not conv:
        return jsonify({"ok": False, "error": "Conversation not found."}), 404

    if request.method == "DELETE":
        AIConversationMessage.query.filter_by(conversation_id=conv.id).delete(synchronize_session=False)
        db.session.delete(conv)
        db.session.commit()
        return jsonify({"ok": True})

    if request.method == "PATCH":
        payload = request.get_json(silent=True) or {}
        changed = False
        if "title" in payload:
            t = str(payload.get("title") or "").strip()[:240]
            if t:
                conv.title = t
                changed = True
        if "is_pinned" in payload:
            conv.is_pinned = bool(payload.get("is_pinned"))
            changed = True
        if not changed:
            return jsonify({"ok": False, "error": "Provide title or is_pinned."}), 400
        db.session.commit()
        return jsonify(
            {
                "ok": True,
                "conversation": {
                    "id": conv.id,
                    "title": conv.title,
                    "is_pinned": bool(conv.is_pinned),
                    "updated_at": conv.updated_at.isoformat() if conv.updated_at else "",
                },
            }
        )

    msgs = (
        AIConversationMessage.query
        .filter_by(conversation_id=conv.id)
        .order_by(AIConversationMessage.created_at.asc())
        .all()
    )
    items = []
    for m in msgs:
        chart_data = None
        if m.chart_json:
            try:
                chart_data = json.loads(m.chart_json)
            except Exception:
                chart_data = None
        items.append(
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "sql_query": m.sql_query,
                "chart_data": chart_data,
                "created_at": m.created_at.isoformat() if m.created_at else "",
            }
        )
    return jsonify(
        {
            "ok": True,
            "conversation": {
                "id": conv.id,
                "title": conv.title,
                "is_pinned": bool(conv.is_pinned),
                "updated_at": conv.updated_at.isoformat() if conv.updated_at else "",
            },
            "messages": items,
        }
    )

