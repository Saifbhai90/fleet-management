Fleet Personal PC (daedalOS static export)
==========================================

After building daedalOS with FLEET_OS_BASE_PATH=/static/fleet_personal_pc (see daedalOS/FLEET_EMBED.md),
copy the export here so Flask serves:

  /static/fleet_personal_pc/index.html

Quick copy (repo root):

  Windows (PowerShell):  .\scripts\copy_fleet_personal_pc_static.ps1
  Linux / Render:       chmod +x scripts/build_fleet_personal_pc.sh && ./scripts/build_fleet_personal_pc.sh
                        (on Render set env BOOTSTRAP_NODE_FOR_BUILD=1 if Node is not installed)

Built assets are gitignored because they are large (~300MB). Run after each daedalOS production
build before deploy, or in CI / Render build step.
