# Online Deploy / Update Guide

## GitHub + Render (aapka setup) — Update kaise karein

Aapne pehle GitHub par upload kiya tha aur Render use kiya tha. **Update** karne ke liye ye steps follow karo:

### Step 1: Git identity (sirf pehli baar)

PowerShell mein:
```powershell
cd d:\company_management
git config user.email "your-email@example.com"
git config user.name "Your Name"
```
(apna email aur naam daalo)

### Step 2: Commit

```powershell
git add .
git commit -m "Update: Maintenance form, Oil, Products, Fuel layout"
```

### Step 3: GitHub se connect karo

**Agar pehle se GitHub repo hai** (same repo update karna hai):
```powershell
git remote add origin https://github.com/YOUR-USERNAME/YOUR-REPO-NAME.git
```
(GitHub par jao → repo kholo → Code → HTTPS URL copy karo. `YOUR-USERNAME` aur `YOUR-REPO-NAME` replace karo.)

Agar pehle hi `origin` add tha aur ab sirf update karna hai, to skip karo ya check karo:
```powershell
git remote -v
```
Agar `origin` dikhe to Step 4 par jao.

### Step 4: Branch — `main` ya `master`

Render usually `main` use karta hai. Agar aapki GitHub repo `main` use karti hai:
```powershell
git branch -M main
git push -u origin main
```

Agar aapki repo `master` use karti hai:
```powershell
git push -u origin master
```

### Step 5: Render par deploy

- **Auto-deploy on hai** → Push karte hi Render naya deploy shuru kar dega.
- **Auto-deploy off hai** → Render Dashboard → apna Web Service → **Manual Deploy** → "Deploy latest commit".

### Step 6: Migrations (agar naye tables / schema change hai)

Render Dashboard → apna service → **Shell** tab (ya "Run background job" / one-off):
```bash
flask db upgrade
```
Ya **Settings** → **Build Command** ke baad **Start Command** ke pehle migrations add kar sakte ho (advanced).

---

## Pehli baar deploy (naya Render setup)

1. **Render** par account → New → **Web Service**.
2. **GitHub repo** connect karo (same repo jo upar push kiya).
3. **Build:** `pip install -r requirements.txt`
4. **Start:** `gunicorn app:app` (ya Render auto-detect karega Procfile se).
5. **Environment:** `SECRET_KEY`, `DATABASE_URL` (Render PostgreSQL add karo to `DATABASE_URL` mil jata hai).
6. Deploy.

---

## Important

- **DATABASE_URL** Render par set hona chahiye (PostgreSQL).
- **SECRET_KEY** strong random string rakho.
- **uploads** — Render ki filesystem ephemeral hoti hai; agar uploads permanent chahiye to Render **Disk** attach karo aur `UPLOAD_FOLDER` us path par point karo.

---

## Optional: Heroku / PythonAnywhere

### Heroku

```bash
heroku login
heroku git:remote -a YOUR-APP-NAME
git push heroku main
heroku run flask db upgrade
```

### PythonAnywhere / VPS

Git se code pull karo, phir:
```bash
pip install -r requirements.txt
flask db upgrade
```
Web server reload karo.
