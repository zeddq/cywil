#!/bin/bash

# Script to generate SSL certificates for production use
# For production, you should use Let's Encrypt or your own CA-signed certificates

set -e

# Configuration
DOMAIN=${1:-localhost}
CERT_DIR="./certificates"
DAYS_VALID=365

echo "Generating SSL certificates for domain: $DOMAIN"

# Create certificates directory
mkdir -p $CERT_DIR

# Generate private key
openssl genrsa -out $CERT_DIR/privkey.pem 2048

# Generate certificate signing request
openssl req -new -key $CERT_DIR/privkey.pem -out $CERT_DIR/csr.pem \
    -subj "/C=US/ST=State/L=City/O=AI Paralegal/CN=$DOMAIN"

# Generate self-signed certificate
openssl x509 -req -days $DAYS_VALID -in $CERT_DIR/csr.pem \
    -signkey $CERT_DIR/privkey.pem -out $CERT_DIR/fullchain.pem

# Clean up CSR
rm $CERT_DIR/csr.pem

# Set proper permissions
chmod 600 $CERT_DIR/privkey.pem
chmod 644 $CERT_DIR/fullchain.pem

echo "Certificates generated successfully in $CERT_DIR/"
echo ""
echo "For production use, replace these with Let's Encrypt certificates:"
echo "  - Install certbot"
echo "  - Run: certbot certonly --standalone -d $DOMAIN"
echo "  - Copy certificates to $CERT_DIR/"