# Render Sleep, Data Clear & 500+ Users — Solution Guide

## Problem 1: Render sleep + data clear ho jata hai

**Kyun hota hai:**
- **Free tier** par Render service **inactivity** ke baad **sleep** (spin down) ho jati hai. Phir jab koi user aata hai to service **wake** hoti hai.
- Agar aap **SQLite** use kar rahe ho (ya `DATABASE_URL` set nahi hai), to database ek **file** hai jo server ki **ephemeral disk** par hoti hai. Jab service restart/sleep se wake hoti hai ya redeploy hota hai, to ye disk **reset** ho sakti hai — isliye **saved data clear** ho jata hai.

**Solution — Persistent database use karo:**

1. **Render Dashboard** → apna **Web Service** → **Environment**.
2. **Add Database:** Left side **New** → **PostgreSQL**. Ek new PostgreSQL instance banao (free tier bhi chal jata hai shuru mein).
3. PostgreSQL create hone ke baad Render **Internal Database URL** dikhata hai. Us ko copy karo.
4. Apne **Web Service** (fleet-management) par jao → **Environment** → **Add Environment Variable**:
   - Key: `DATABASE_URL`
   - Value: wahi **Internal Database URL** (paste karo).
5. **Save** karo. Render service **redeploy** karega.
6. Redeploy ke baad **Shell** (Web Service → Shell) open karo aur run karo:
   ```bash
   flask db upgrade
   ```
   Isse saari tables PostgreSQL mein ban jayengi.

Ab data **database** (PostgreSQL) mein rahega, **disk** par nahi. Sleep/wake ya redeploy ke baad bhi **data clear nahi hoga**.

---

## Problem 2: Sleep mode — app thodi der baad on hoti hai

**Kyun:** Free tier par service inactive rehne par band ho jati hai; pehla request aane par start hoti hai (cold start), isliye 30 sec–1 min lag feel hota hai.

**Options:**

| Option | Kya karna hai | Sleep hoga? |
|--------|----------------|-------------|
| **A) Render Paid (Starter)** | Plan upgrade → **Always On** | Nahi — 24/7 on |
| **B) Free tier + UptimeRobot** | [UptimeRobot](https://uptimerobot.com) (free) par apna app URL add karo, har 5–10 min ping | Kam — jab ping jayega tab wake, lekin real user pe pehli request ab bhi slow |
| **C) Railway / Fly.io** | Wahi code deploy, inka free tier thoda different | Depends on plan |

**Recommendation:** 500+ users ke liye **Render paid plan** (Starter) le lo — **Always On**, no sleep, better performance.

---

## 500+ users ke liye steps

1. **PostgreSQL use karo** (upar wala step — data persist, multiple workers safe).
2. **Render paid plan** (Starter ya higher) — Always On, zyada RAM/CPU.
3. **Environment variables** sahi rakhna:
   - `DATABASE_URL` = PostgreSQL Internal URL
   - `SECRET_KEY` = strong random string
4. **Migrations** deploy ke baad zaroor: `flask db upgrade` (Shell se ya Build/Start command mein).
5. Agar traffic aur badhe to baad mein **Redis** (caching/sessions) ya **multiple instances** add kar sakte ho — abhi 500 users ke liye single instance + PostgreSQL kaafi hai.

---

## Future: Web + Mobile App dono

**Architecture jo rakhna hai:**

- **Ek backend** (yehi Flask app) — sab business logic, database, auth.
- **Ek database** (PostgreSQL) — web aur mobile dono isi ko use karenge.
- **Web:** Ab jaisa hai (browser) — same Flask templates ya baad mein React/Vue frontend.
- **Mobile App:** React Native / Flutter / native app jo **API calls** karega isi backend par.

**Steps:**

1. **Backend ko API-ready rakho** — jahan zarurat ho wahan **JSON responses** bhi do (ab bhi kuch routes JSON return karte hain). Future mein mobile app same URLs ko call karega.
2. **Database** sirf backend par — mobile direct DB ko access nahi karega, sirf API.
3. **Authentication** — agar mobile app mein login chahiye to **token-based** (e.g. JWT) add karna hoga; abhi web session-based hai, baad mein dono support kar sakte ho.
4. **Same codebase** — backend ek hi, web site bhi isi se, mobile app bhi isi backend se connect karega.

Is tarah **web par bhi chalegi, mobile app par bhi** — dono same server + same database use karenge.

---

## Pre-deploy: `flask db upgrade` fail (build OK, pre-deploy error)

Agar build **Success** dikh raha hai lekin **Pre-Deploy** (`python -m flask db upgrade`) **fail** ho jata hai, Render kabhi "cause could not be determined" dikhata hai. Asli error **log** mein hota hai — **Dashboard → deploy → Pre-Deploy** expand karke dekhain.

**Yeh variables zaroori hain (Web Service → Environment):**

| Variable | Kya rakhna hai |
|----------|----------------|
| `SECRET_KEY` | Koi bhi long random string — bina iske `app` import hote waqt error (app.py `RuntimeError: SECRET_KEY must be set in production/Render`). |
| `DATABASE_URL` | PostgreSQL **Internal** URL (web service jis DB se judegi). |
| `FLASK_APP` (optional) | `app:app` — agar set na ho to `flask` command kabhi kabhi "Could not locate application" de sakta hai. |

**Pre-Deploy command** Render par aise rakhain (reliable):

```text
sh scripts/render_migrate.sh
```

Repo mein `scripts/render_migrate.sh` maujood hai: pehle `SECRET_KEY` / `DATABASE_URL` check karta hai, phir `flask db upgrade` chalata hai — missing env par log mein **clear** message aata hai.

**Shell se debug:** Web Service → **Shell** open karke chalain (same env as deploy):

```bash
sh scripts/render_migrate.sh
# ya
export FLASK_APP=app:app
python -m flask db upgrade
```

Agar yahan par **full Python traceback** dikhe, wahi asli wajah hai (e.g. DB connection, Alembic duplicate head, etc.).

---

## Short checklist

- [ ] Render par **PostgreSQL** add kiya, **DATABASE_URL** Web Service Environment mein set kiya.
- [ ] **`SECRET_KEY`** bhi set hai (migrations + app import ke liye).
- [ ] (Optional) **`FLASK_APP=app:app`**
- [ ] Redeploy ke baad pre-deploy chal gaya, ya **Shell** se `sh scripts/render_migrate.sh` / `flask db upgrade` chala diya.
- [ ] Data ab clear nahi hota — check karo (entry add karo, sleep/wake karo, phir dekho).
- [ ] 500+ users / no sleep ke liye **paid plan** consider kiya.
- [ ] Future mobile ke liye backend ko API + same DB par hi rakhna hai.

---

**Note:** `app.py` mein Render ke `postgres://` URL ko `postgresql://` mein convert kiya gaya hai (SQLAlchemy compatibility). Aur `requirements.txt` mein `psycopg2-binary` add kiya hai taake Render par PostgreSQL chal sake.
