const { app, BrowserWindow, shell } = require('electron');
const path = require('path');

/** Same default as capacitor.config.json server.url — override with env FLEET_MANAGER_URL */
const DEFAULT_ORIGIN = 'https://fleet-management-xdvj.onrender.com';

function fleetBaseUrl() {
  const u = (process.env.FLEET_MANAGER_URL || DEFAULT_ORIGIN).trim().replace(/\/+$/, '');
  try {
    new URL(u);
    return u;
  } catch {
    return DEFAULT_ORIGIN;
  }
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  win.once('ready-to-show', () => win.show());

  const url = `${fleetBaseUrl()}/`;
  win.loadURL(url).catch(() => {
    win.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(
      `<!DOCTYPE html><html><head><meta charset="utf-8"><title>Fleet Manager</title></head>
<body style="font-family:system-ui;padding:2rem;max-width:36rem">
<h1>Could not load Fleet Manager</h1>
<p>Check internet connection and <code>FLEET_MANAGER_URL</code>.</p>
<p>Trying: <code>${url}</code></p>
</body></html>`
    )}`);
  });

  win.webContents.setWindowOpenHandler(({ url: target }) => {
    shell.openExternal(target);
    return { action: 'deny' };
  });
}

app.whenReady().then(() => {
  createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
