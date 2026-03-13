const sharp = require('./node_modules/sharp');
const fs = require('fs');
const path = require('path');

const svgPath = path.join(__dirname, 'static', 'images', 'icon.svg');
const outIcon = path.join(__dirname, 'resources', 'icon.png');
const outSplash = path.join(__dirname, 'resources', 'splash.png');

const svgBuf = fs.readFileSync(svgPath);

// Generate 1024x1024 icon
sharp(svgBuf)
  .resize(1024, 1024)
  .png()
  .toFile(outIcon)
  .then(() => {
    console.log('✅ resources/icon.png created (1024x1024)');

    // Generate 2732x2732 splash (dark navy background + centered icon)
    return sharp({
      create: {
        width: 2732, height: 2732,
        channels: 4,
        background: { r: 30, g: 41, b: 59, alpha: 1 }
      }
    })
    .composite([{
      input: svgBuf,
      blend: 'over',
      gravity: 'centre',
      density: 300
    }])
    .resize(2732, 2732)
    .png()
    .toFile(outSplash);
  })
  .then(() => console.log('✅ resources/splash.png created (2732x2732)'))
  .catch(err => {
    console.error('❌ Error:', err.message);
    process.exit(1);
  });
