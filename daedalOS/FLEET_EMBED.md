# Embedding Fleet Personal PC (daedalOS) under Fleet Manager

The Flask route **Admin → Personal Tools** (`/admin/personal-tools`) loads the desktop shell from:

`static/fleet_personal_pc/index.html`

That directory must contain a **Next.js static export** of this project with the correct URL prefix.

## 1. Configure the base path

When the app is hosted under `https://YOUR_DOMAIN/static/fleet_personal_pc/`, Next.js must be built with:

| Variable | Example value |
|----------|----------------|
| `FLEET_OS_BASE_PATH` | `/static/fleet_personal_pc` |

**PowerShell (Windows)**

```powershell
cd daedalOS
$env:FLEET_OS_BASE_PATH = "/static/fleet_personal_pc"
npm install --legacy-peer-deps
npm run build
```

Dependencies use **`browserfs@1.4.3`** from npm (pinned for TypeScript/build compatibility with the bundled `browserfs.min.js`) and **`Burn-My-Windows`** vendored under `vendor/Burn-My-Windows` (git installs often fail on Windows; no separate `yarn` needed for build).

After a successful build, from the **company_management** repo root run:

```powershell
.\scripts\copy_fleet_personal_pc_static.ps1
```

That copies `daedalOS/out/` into `static/fleet_personal_pc/` for Flask (large folder; kept out of git by `.gitignore`).

For local development **without** a subpath (e.g. `http://localhost:3000`), omit `FLEET_OS_BASE_PATH` so it stays empty.

## 2. Copy build output

After `npm run build`, copy everything inside `daedalOS/out/` to:

`company_management/static/fleet_personal_pc/`

Overwrite existing files. Ensure `index.html` exists next to `_next/` and other assets.

## 3. Desktop shortcuts → Fleet tools

Desktop `.url` files under `public/Users/Public/Desktop/` open the **Browser** app with **same-origin** paths:

| Shortcut | Path |
|----------|------|
| Fleet Notes | `/admin/personal-tools/os-notes` |
| Fleet Calculator | `/admin/personal-tools/os-calculator` |
| Fleet Multi File Print | `/admin/personal-tools/quick-print` |

You must be logged in as a master admin in the same browser session so those routes work inside the Browser iframe.

Relative paths are resolved via `getUrlOrSearch` (see `utils/functions.ts`).

## 4. Branding configuration

| Goal | Location |
|------|-----------|
| Window/tab title (`Fleet Personal PC`) | `utils/constants.ts` → `PACKAGE_DATA.alias` |
| Default wallpaper id | `utils/constants.ts` → `DEFAULT_WALLPAPER` — optional ids are listed in `components/system/Desktop/Wallpapers/constants.ts` (`WALLPAPER_MENU`). Users can also change wallpaper from the desktop context menu → Personalize. |
| Tab icon (default, when no app overrides it) | Replace `public/fleet-brand/favicon.svg` and/or adjust `FAVICON_BASE_PATH` in `utils/constants.ts`. |
| Taskbar Start orb | `components/system/Taskbar/StartButton/StartButtonIcon.tsx` — swap SVG or load an image from `public/fleet-brand/`. |

## 5. Start Menu cleanup

Games, emulators, and non-essential shortcuts were removed from `public/Users/Public/Start Menu/`. Re-run the official daedalOS prebuild scripts (`yarn build:prebuild`) after edits so virtual FS indexes stay consistent:

```bash
yarn build:prebuild && yarn build
```

## 6. Large assets (`public/Program Files/`)

This fork adds `public/Program Files/` to `.gitignore` so Monaco, PDF.js, Pyodide, etc. are **not** committed. Copy them from an upstream daedalOS checkout or release bundle — without them, many built-in apps will not load until those folders exist locally.

## 7. Troubleshooting

- **Blank iframe**: Confirm `static/fleet_personal_pc/index.html` exists on the server and `FLEET_OS_BASE_PATH` matched the deployed folder at build time.
- **`npm install` fails on git deps**: Try `npm install --legacy-peer-deps`; ensure Git is installed for GitHub-hosted packages (e.g. Burn-My-Windows, BrowserFS).
- **Shortcuts open wrong site**: Fleet URLs must match your deployed origin; paths always start with `/admin/...`.
