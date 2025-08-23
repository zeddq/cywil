# AI Paralegal POC Deployment Guide

This guide provides instructions for deploying the AI Paralegal POC application to a Kubernetes cluster.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Quick Start](#quick-start)
3. [Deployment Architecture](#deployment-architecture)
4. [Setup Instructions](#setup-instructions)
5. [Deployment Scripts](#deployment-scripts)
6. [Cluster Management](#cluster-management)
7. [Monitoring](#monitoring)
8. [Troubleshooting](#troubleshooting)

## Prerequisites

- Linux VM or server (minimum 4 CPU, 8GB RAM, 50GB disk)
- SSH access to the VM (if deploying remotely)
- Root/sudo access on the target machine
- Basic understanding of Kubernetes

**Note**: The setup script will automatically install:
- Docker CE with buildx and compose plugins
- tar, curl, wget, and other essential tools
- kubectl and helm
- Local Docker registry (port 5000)
- k3s with Traefik ingress controller

## Quick Start

1. **Setup k3s cluster on a VM:**
   ```bash
   cd deployment/scripts
   chmod +x *.sh
   sudo ./setup-k3s.sh [VM_HOSTNAME]  # omit hostname for local install
   ```
   
   This will install and configure:
   - Docker CE with local registry on port 5000
   - k3s Kubernetes cluster
   - kubectl, helm, and storage provisioner
   - Traefik ingress controller
   - Optional monitoring stack (Prometheus + Grafana)

2. **Configure secrets:**
   ```bash
   cp deployment/k8s/secrets.yaml deployment/k8s/secrets-prod.yaml
   # Edit secrets-prod.yaml with your actual values
   kubectl apply -f deployment/k8s/secrets-prod.yaml
   ```

3. **Build and deploy:**
   ```bash
   # Deploy both backend and UI
   ./build-and-deploy.sh -h VM_HOSTNAME full
   
   # Deploy only backend
   ./build-and-deploy.sh -h VM_HOSTNAME -c backend full
   
   # Deploy only UI
   ./build-and-deploy.sh -h VM_HOSTNAME -c ui full
   ```

## Deployment Architecture

```
┌─────────────────────────────────────────────────┐
│                 k3s Cluster                     │
├─────────────────────────────────────────────────┤
│  Namespace: ai-paralegal                        │
│                                                 │
│  ┌─────────────┐  ┌─────────────┐             │
│  │   App Pod   │  │   UI Pod    │             │
│  │  Port 8000  │  │  Port 3000  │             │
│  └──────┬──────┘  └──────┬──────┘             │
│         │                 │                     │
│  ┌──────┴─────────────────┴──────┐            │
│  │        Services               │            │
│  │  ai-paralegal-service (80)    │            │
│  │  ai-paralegal-ui-service (80) │            │
│  └───────────────┬───────────────┘            │
│                  │                             │
│  ┌───────────────┴───────────────┐            │
│  │          Ingress              │            │
│  │    paralegal.local:80         │            │
│  │    /api/* → backend           │            │
│  │    /*     → ui                │            │
│  └───────────────────────────────┘            │
│                                                │
│  Databases:                                    │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐│
│  │ PostgreSQL │ │   Redis    │ │   Qdrant   ││
│  │  (10Gi)    │ │   (2Gi)    │ │  (20Gi)    ││
│  └────────────┘ └────────────┘ └────────────┘│
└─────────────────────────────────────────────────┘
```

## Setup Instructions

### 1. Install k3s Cluster

For a single-node cluster on a VM:

```bash
# Local installation
sudo ./deployment/scripts/setup-k3s.sh

# Remote installation via SSH (run on the target VM)
sudo ./deployment/scripts/setup-k3s.sh
```

This script will:
- Install Docker CE with local registry (port 5000)
- Install system dependencies (tar, curl, wget, etc.)
- Install k3s (lightweight Kubernetes)
- Setup kubectl and helm
- Configure local-path storage
- Install Traefik ingress controller
- Optional: Setup basic monitoring

**Important**: The script sets up a local Docker registry at `localhost:5000` which is used by the build-and-deploy script for storing container images locally.

### 2. Configure Application

1. **Update secrets** (deployment/k8s/secrets.yaml):
   - `OPENAI_API_KEY`: Your OpenAI API key
   - `POSTGRES_PASSWORD`: Database password
   - `REDIS_PASSWORD`: Redis password
   - `QDRANT_API_KEY`: Qdrant API key
   - `SECRET_KEY`: Application secret key
   - `ADMIN_TOKEN`: Admin maintenance token

2. **Update configuration** (deployment/k8s/configmap.yaml):
   - Model names (GPT-4, embeddings)
   - Performance settings
   - Circuit breaker thresholds
   - UI configuration (port, timeouts, analytics)

3. **Update ingress** (deployment/k8s/ingress.yaml):
   - Change `paralegal.local` to your domain
   - Add TLS configuration if HTTPS is needed
   - Routes are preconfigured: `/api/*` → backend, `/*` → UI

### 3. Build and Deploy

The `build-and-deploy.sh` script provides several operations:

```bash
# Build Docker images locally (both backend and UI)
./deployment/scripts/build-and-deploy.sh build

# Build only backend
./deployment/scripts/build-and-deploy.sh -c backend build

# Build only UI
./deployment/scripts/build-and-deploy.sh -c ui build

# Deploy to Kubernetes (all components)
./deployment/scripts/build-and-deploy.sh deploy

# Deploy only UI (useful for UI updates)
./deployment/scripts/build-and-deploy.sh -c ui deploy

# Full build and deploy
./deployment/scripts/build-and-deploy.sh full

# Update from working copy via SSH
./deployment/scripts/build-and-deploy.sh -h vm-hostname update-image

# Redeploy pods (rolling restart)
./deployment/scripts/build-and-deploy.sh redeploy
```

## Deployment Scripts

### build-and-deploy.sh

Main deployment script with options:

```bash
Usage: ./build-and-deploy.sh [OPTIONS] COMMAND

Commands:
  build           Build Docker image locally
  deploy          Deploy to Kubernetes cluster
  full            Build and deploy
  redeploy        Redeploy existing image
  update-image    Update pod images from working copy

Options:
  -h, --host      SSH hostname for remote operations
  -f, --force     Force rebuild even if no changes
  -s, --skip-tests Skip running tests before build
  -t, --tag       Docker image tag (default: latest)
  -r, --registry  Docker registry (default: localhost:5000)
```

### cluster-management.sh

Cluster management utilities:

```bash
Usage: ./cluster-management.sh [OPTIONS] COMMAND

Commands:
  status          Show cluster and application status
  logs            Show application logs
  restart         Restart all services
  backup          Backup databases and configurations
  restore         Restore from backup
  scale           Scale application replicas
  debug           Enter debug shell in app container
  health          Check health of all services
  reset           Reset cluster (WARNING: deletes all data)

Options:
  -h, --host      SSH hostname for remote operations
  -n, --namespace Kubernetes namespace (default: ai-paralegal)
```

### Examples

1. **Deploy to remote VM:**
   ```bash
   ./build-and-deploy.sh -h my-vm-hostname full
   ```

2. **Update from local working copy:**
   ```bash
   ./build-and-deploy.sh -h my-vm-hostname update-image
   ```

3. **Check cluster status:**
   ```bash
   ./cluster-management.sh -h my-vm-hostname status
   ```

4. **View logs:**
   ```bash
   ./cluster-management.sh -h my-vm-hostname logs
   ```

5. **Scale application:**
   ```bash
   ./cluster-management.sh -h my-vm-hostname scale
   # Enter number of replicas when prompted
   ```

## Monitoring

### Setup Monitoring Stack

```bash
./deployment/scripts/setup-monitoring.sh
```

This installs:
- Prometheus (metrics collection)
- Grafana (visualization)
- Loki (log aggregation)
- Default dashboards and alerts

### Access Monitoring Tools

```bash
# Prometheus
kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 9090:9090

# Grafana (default admin/admin)
kubectl port-forward -n monitoring svc/prometheus-grafana 3000:80

# Application metrics
curl http://paralegal.local/metrics
```

## Troubleshooting

### Common Issues

1. **Pods not starting:**
   ```bash
   kubectl describe pod <pod-name> -n ai-paralegal
   kubectl logs <pod-name> -n ai-paralegal
   ```

2. **Database connection issues:**
   - Check secrets are properly configured
   - Verify services are running: `kubectl get svc -n ai-paralegal`
   - Test connectivity from app pod

3. **Storage issues:**
   ```bash
   kubectl get pvc -n ai-paralegal
   kubectl describe pvc <pvc-name> -n ai-paralegal
   ```

4. **Ingress not working:**
   - Add hostname to /etc/hosts: `<VM-IP> paralegal.local`
   - Access via HTTP: `http://paralegal.local`
   - Check Traefik logs: `kubectl logs -n kube-system -l app.kubernetes.io/name=traefik`

### Debug Commands

```bash
# Enter app container
./cluster-management.sh debug

# Check health
./cluster-management.sh health

# View all resources
kubectl get all -n ai-paralegal

# Describe deployment
kubectl describe deployment ai-paralegal-app -n ai-paralegal

# Force pod recreation
kubectl delete pod -l app=ai-paralegal -n ai-paralegal
```

### Backup and Restore

```bash
# Create backup
./cluster-management.sh backup

# List backups
ls -la ./backups/

# Restore from backup
./cluster-management.sh restore
# Enter backup directory name when prompted
```

## Security Considerations

1. **Change default passwords** in secrets.yaml
2. **Enable TLS** for ingress with proper certificates
3. **Restrict access** to cluster API and SSH
4. **Regular backups** of databases
5. **Monitor logs** for suspicious activity
6. **Keep k3s updated** with security patches

## Performance Tuning

1. **Adjust resource limits** in deployment manifests based on load
2. **Scale replicas** based on traffic: `./cluster-management.sh scale`
3. **Configure connection pools** in configmap.yaml
4. **Monitor metrics** via Grafana dashboards
5. **Enable caching** where appropriate

## Maintenance

### Regular Tasks

1. **Daily:**
   - Check application health
   - Monitor error logs
   - Review metrics

2. **Weekly:**
   - Backup databases
   - Check disk usage
   - Review security logs

3. **Monthly:**
   - Update dependencies
   - Apply security patches
   - Performance review

### Update Procedure

1. **Test in development**
2. **Create backup:** `./cluster-management.sh backup`
3. **Deploy update:** `./build-and-deploy.sh -h vm-hostname update-image`
4. **Monitor logs:** `./cluster-management.sh logs`
5. **Rollback if needed:** `kubectl rollout undo deployment/ai-paralegal-app -n ai-paralegal`
