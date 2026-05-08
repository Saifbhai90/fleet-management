Fleet Personal PC (daedalOS build output)
==========================================

Place the contents of `daedalOS/out/` here after a production build so that:

  /static/fleet_personal_pc/index.html

is served by Flask and the Personal Tools desktop iframe loads correctly.

Build steps are documented in the repo at:

  daedalOS/FLEET_EMBED.md

Until this folder contains `index.html`, the Personal Tools page shows an empty iframe until you deploy the build.
