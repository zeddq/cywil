# Deployment Guide for AI Paralegal with HTTPS

This guide explains how to deploy the AI Paralegal application with HTTPS support on a remote server.

## Prerequisites

- Docker and Docker Compose installed on the remote server
- Domain name pointing to your server (for production SSL certificates)
- OpenAI API key

## Quick Start

1. **Clone the repository on your remote server:**
   ```bash
   git clone <your-repo-url>
   cd ai-paralegal-poc
   ```

2. **Set up environment variables:**
   ```bash
   cp .env.example .env
   # Edit .env with your actual values
   ```

3. **Generate SSL certificates:**
   
   For development/testing with self-signed certificates:
   ```bash
   ./generate-certificates.sh your-domain.com
   ```
   
   For production with Let's Encrypt:
   ```bash
   # Install certbot first
   sudo apt-get update
   sudo apt-get install certbot
   
   # Generate certificates
   sudo certbot certonly --standalone -d your-domain.com -d www.your-domain.com
   
   # Copy certificates to the project
   sudo cp /etc/letsencrypt/live/your-domain.com/fullchain.pem ./certificates/
   sudo cp /etc/letsencrypt/live/your-domain.com/privkey.pem ./certificates/
   sudo chown $USER:$USER ./certificates/*
   chmod 644 ./certificates/fullchain.pem
   chmod 600 ./certificates/privkey.pem
   ```

4. **Deploy with Docker Compose:**
   ```bash
   docker-compose -f docker-compose.prod.yml up -d
   ```

## Architecture

The production setup includes:

- **Nginx**: Reverse proxy handling SSL termination and routing
- **UI**: Next.js application served over HTTPS
- **API**: FastAPI backend
- **PostgreSQL**: Main database
- **Redis**: Caching layer
- **Qdrant**: Vector database for document embeddings

## SSL/TLS Configuration

The Nginx configuration includes:
- HTTP to HTTPS redirect
- TLS 1.2 and 1.3 support
- Strong cipher suites
- HSTS headers
- Security headers (X-Frame-Options, X-Content-Type-Options, etc.)

## Ports

- Port 80: HTTP (redirects to HTTPS)
- Port 443: HTTPS (main application)
- Internal ports are not exposed to the host

## Monitoring

Check application logs:
```bash
# All services
docker-compose -f docker-compose.prod.yml logs -f

# Specific service
docker-compose -f docker-compose.prod.yml logs -f ui
docker-compose -f docker-compose.prod.yml logs -f api
```

## Updating

To update the application:
```bash
git pull
docker-compose -f docker-compose.prod.yml build
docker-compose -f docker-compose.prod.yml up -d
```

## SSL Certificate Renewal

For Let's Encrypt certificates, set up auto-renewal:
```bash
# Add to crontab
0 0 * * 0 certbot renew --quiet && docker-compose -f docker-compose.prod.yml restart nginx
```

## Backup

Important directories to backup:
- `./certificates/` - SSL certificates
- PostgreSQL data volume
- Qdrant data volume

## Troubleshooting

1. **Certificate errors**: Ensure certificates are in the correct location and have proper permissions
2. **502 Bad Gateway**: Check if all services are running with `docker-compose ps`
3. **Connection refused**: Verify firewall rules allow ports 80 and 443

## Security Considerations

- Keep your `.env` file secure and never commit it to version control
- Regularly update Docker images
- Monitor logs for suspicious activity
- Use strong passwords for all services
- Consider implementing rate limiting in Nginx