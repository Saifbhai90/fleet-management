/**
 * DEPRECATED: App icons use static/images/icon.svg — run generate_icon.js instead.
 * Generate PWA / Capacitor assets from static/images/fleet-brand-hero.png
 * Run: node generate_fleet_brand.js
 */
const sharp = require('./node_modules/sharp');
const fs = require('fs');
const path = require('path');

const src = path.join(__dirname, 'static', 'images', 'fleet-brand-hero.png');
if (!fs.existsSync(src)) {
  console.error('Missing:', src);
  process.exit(1);
}

const out192 = path.join(__dirname, 'static', 'images', 'icon-192.png');
const out512 = path.join(__dirname, 'static', 'images', 'icon-512.png');
const outIcon = path.join(__dirname, 'resources', 'icon.png');
const outSplash = path.join(__dirname, 'resources', 'splash.png');

const bg = { r: 224, g: 242, b: 254, alpha: 1 };

async function run() {
  await sharp(src).resize(1024, 1024, { fit: 'cover', position: 'centre' }).png().toFile(outIcon);
  await sharp(src).resize(192, 192, { fit: 'cover', position: 'centre' }).png().toFile(out192);
  await sharp(src).resize(512, 512, { fit: 'cover', position: 'centre' }).png().toFile(out512);

  const centred = await sharp(src).resize(1400, 1400, { fit: 'contain', background: bg }).toBuffer();
  await sharp({ create: { width: 2732, height: 2732, channels: 4, background: bg } })
    .composite([{ input: centred, gravity: 'centre' }])
    .png()
    .toFile(outSplash);

  console.log('Created:', out192, out512, outIcon, outSplash);
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
