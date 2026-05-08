Fleet Personal PC (daedalOS static export)
==========================================

After building daedalOS with FLEET_OS_BASE_PATH=/static/fleet_personal_pc (see daedalOS/FLEET_EMBED.md),
copy the export here so Flask serves:

  /static/fleet_personal_pc/index.html

Quick copy (repo root, PowerShell):

  .\scripts\copy_fleet_personal_pc_static.ps1

Built assets are gitignored because they are large (~300MB). Run the script after each daedalOS
production build before deploy, or run it in CI after `npm run build` inside daedalOS.
