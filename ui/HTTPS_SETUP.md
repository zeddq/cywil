# HTTPS Setup for AI Paralegal UI

This guide explains how to run the Next.js UI with HTTPS support for local development.

## Quick Start

### Method 1: Local Development

1. Generate self-signed certificates:
   ```bash
   npm run generate-certs
   ```

2. Start the HTTPS server:
   ```bash
   npm run dev:https
   ```

3. Access the application at: https://localhost:3443

### Method 2: Docker Development

1. Build and run with Docker Compose:
   ```bash
   docker-compose -f docker-compose.https.yml up --build
   ```

2. Access the application at: https://localhost:3443

## Certificate Trust

When you first access the HTTPS URL, your browser will warn about the self-signed certificate. To trust it:

### Chrome/Edge:
1. Click "Advanced"
2. Click "Proceed to localhost (unsafe)"

### Firefox:
1. Click "Advanced"
2. Click "Accept the Risk and Continue"

### macOS (System-wide trust):
```bash
cd ui/certificates
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain localhost.pem
```

### Linux (Chrome/Chromium):
```bash
cd ui/certificates
certutil -d sql:$HOME/.pki/nssdb -A -t "CT,c,c" -n "localhost" -i localhost.pem
```

## Configuration

- HTTPS Port: 3443
- HTTP API Proxy: Still proxies to http://localhost:8000
- Certificates Location: `ui/certificates/`

## Files Added

- `server.js` - Custom HTTPS server for Next.js
- `generate-certificates.sh` - Script to generate self-signed certificates
- `Dockerfile.dev.https` - Docker configuration with HTTPS support
- `docker-compose.https.yml` - Docker Compose configuration for HTTPS
- Updated `package.json` with new scripts:
  - `dev:https` - Run development server with HTTPS
  - `generate-certs` - Generate self-signed certificates

## Switching Between HTTP and HTTPS

- HTTP (default): `npm run dev` (port 3000)
- HTTPS: `npm run dev:https` (port 3443)

Both can run simultaneously if needed.

## Production Considerations

For production, you should:
1. Use proper SSL certificates from a Certificate Authority (CA)
2. Configure your reverse proxy (nginx, Apache, etc.) to handle HTTPS
3. Update the certificate paths in `server.js` to point to your production certificates