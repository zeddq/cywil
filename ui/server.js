const { createServer } = require('https');
const { parse } = require('url');
const fs = require('fs');
const path = require('path');

const dev = process.env.NODE_ENV !== 'production';
const hostname = process.env.HOSTNAME || 'localhost';
const port = parseInt(process.env.PORT || '3443', 10);

if (!dev) {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { config } = require('./.next/required-server-files.json')
  process.env.__NEXT_PRIVATE_STANDALONE_CONFIG = JSON.stringify(config)
}
const next = require('next');
const app = next({ dev, hostname, port });
const handle = app.getRequestHandler();

const httpsOptions = {
  key: fs.readFileSync(path.join(__dirname, 'certificates', 'privkey.pem')),
  cert: fs.readFileSync(path.join(__dirname, 'certificates', 'fullchain.pem')),
};

app.prepare().then(() => {
  createServer(httpsOptions, async (req, res) => {
    try {
      const parsedUrl = parse(req.url, true);
      await handle(req, res, parsedUrl);
    } catch (err) {
      console.error('Error occurred handling', req.url, err);
      res.statusCode = 500;
      res.end('internal server error');
    }
  })
    .once('error', (err) => {
      console.error(err);
      process.exit(1);
    })
    .listen(port, () => {
      console.log(`> Ready on https://${hostname}:${port}`);
    });
});
