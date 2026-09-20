# 16 — Performance

## Production constraints

| Factor | Impact |
|--------|--------|
| Render Starter ~512MB RAM | Gunicorn **1 worker** / 4 threads (2 workers historically OOM) |
| In-process schedulers + GPS polling | Must stay single-worker to avoid duplicate jobs |
| Ephemeral disk | Media on R2; avoid large local writes |
| Mobile networks | Brotli/Gzip compression enabled |

---

## What is already optimized

- SQLAlchemy `pool_pre_ping` + recycle against idle Postgres drops  
- Flask-Compress for HTML/CSS/JS/JSON  
- Image → WebP resize before R2 upload  
- Pagination caps (prior audit: `per_page` capped ~500)  
- Position caches for PortalXS/Ufone (UI reads DB cache, not live SOAP every click)  
- Backup excludes heavy log tables by default on Render  

---

## Bottlenecks & risks

| Area | Risk |
|------|------|
| Fat route modules / huge templates | Slow render, large HTML payloads (fuel form, daily attendance report) |
| `get_user_context` / permission loading | Extra DB queries per request if uncached (audit BUG-005) |
| Large Excel uploads (tasks) | Long requests; Gunicorn timeout 600s helps but ties a thread |
| Playwright tracker automation | Heavy CPU/RAM on same web dyno |
| Unscoped list queries | Full table scans if filters forgotten |
| Activity/client logs growth | DB bloat; excluded from backup but still query cost |
| Workspace/finance reports | Multi-join aggregations on large months |
| Dual polling threads | Continuous background I/O |

---

## Database notes

- Prefer selective columns + joins with indexes already on FKs/date fields.  
- Many models index foreign keys and dates — use them in filters.  
- Avoid N+1: use `joinedload`/`selectinload` where lists include relationships.  
- Alembic chain length (84) slows migrate time, not runtime.

---

## Frontend performance

- Extract mega-template inline JS gradually.  
- Keep Tom Select / OCR libs lazy-loaded where possible (`ws_slip_ocr`).  
- Mobile CSS already targets WebView jank (`legacy_android_gpu`).  

---

## Scaling guidance (from `docs/RENDER_SCALING_GUIDE.md` intent)

If upgrading RAM/plan:

1. Raising Gunicorn workers requires **moving schedulers/polling out** of the web process (or use locks thoroughly).  
2. Otherwise keep `workers=1`.  
3. Consider separate worker service for Playwright + backups.  

---

## Perf checklist for new features

1. Paginate lists.  
2. Index new filter columns.  
3. Cache external API results (follow PortalXS/Ufone pattern).  
4. Offload huge uploads to async status pattern (fuel attachments).  
5. Do not add unbounded `Model.query.all()` on hot paths.
