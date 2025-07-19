#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
NAMESPACE="monitoring"
PROMETHEUS_VERSION="2.45.0"
GRAFANA_VERSION="10.0.3"

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

# Create monitoring namespace
create_namespace() {
    print_step "Creating monitoring namespace..."
    kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
}

# Install Prometheus
install_prometheus() {
    print_step "Installing Prometheus..."
    
    # Add Prometheus helm repo
    helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
    helm repo update
    
    # Create values file
    cat > /tmp/prometheus-values.yaml <<EOF
prometheus:
  prometheusSpec:
    serviceMonitorSelectorNilUsesHelmValues: false
    serviceMonitorSelector: {}
    serviceMonitorNamespaceSelector: {}
    retention: 7d
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: local-path
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 10Gi
    resources:
      requests:
        memory: 400Mi
        cpu: 200m
      limits:
        memory: 2Gi
        cpu: 1000m

grafana:
  enabled: true
  adminPassword: admin
  persistence:
    enabled: true
    storageClassName: local-path
    size: 5Gi
  service:
    type: ClusterIP

alertmanager:
  enabled: false

prometheus-node-exporter:
  enabled: true

kube-state-metrics:
  enabled: true
EOF
    
    # Install Prometheus Operator
    helm upgrade --install prometheus prometheus-community/kube-prometheus-stack \
        --namespace "$NAMESPACE" \
        --values /tmp/prometheus-values.yaml \
        --wait
    
    rm -f /tmp/prometheus-values.yaml
    print_status "Prometheus installed successfully"
}

# Create ServiceMonitor for AI Paralegal
create_service_monitor() {
    print_step "Creating ServiceMonitor for AI Paralegal..."
    
    cat <<EOF | kubectl apply -f -
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: ai-paralegal-monitor
  namespace: ai-paralegal
  labels:
    app: ai-paralegal
spec:
  selector:
    matchLabels:
      app: ai-paralegal
  endpoints:
  - port: http
    path: /metrics
    interval: 30s
EOF
    
    print_status "ServiceMonitor created"
}

# Create Grafana dashboards
create_dashboards() {
    print_step "Creating Grafana dashboards..."
    
    # AI Paralegal Dashboard
    cat <<'EOF' | kubectl apply -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: ai-paralegal-dashboard
  namespace: monitoring
  labels:
    grafana_dashboard: "1"
data:
  ai-paralegal.json: |
    {
      "dashboard": {
        "title": "AI Paralegal Monitoring",
        "uid": "ai-paralegal",
        "panels": [
          {
            "title": "Request Rate",
            "targets": [
              {
                "expr": "rate(http_requests_total{job=\"ai-paralegal\"}[5m])"
              }
            ],
            "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0}
          },
          {
            "title": "Response Time",
            "targets": [
              {
                "expr": "histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{job=\"ai-paralegal\"}[5m]))"
              }
            ],
            "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0}
          },
          {
            "title": "Error Rate",
            "targets": [
              {
                "expr": "rate(http_requests_total{job=\"ai-paralegal\",status=~\"5..\"}[5m])"
              }
            ],
            "gridPos": {"h": 8, "w": 12, "x": 0, "y": 8}
          },
          {
            "title": "Active Connections",
            "targets": [
              {
                "expr": "http_connections_active{job=\"ai-paralegal\"}"
              }
            ],
            "gridPos": {"h": 8, "w": 12, "x": 12, "y": 8}
          }
        ]
      }
    }
EOF
    
    print_status "Dashboards created"
}

# Setup alerts
setup_alerts() {
    print_step "Setting up alerts..."
    
    cat <<EOF | kubectl apply -f -
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: ai-paralegal-alerts
  namespace: ai-paralegal
  labels:
    prometheus: kube-prometheus
spec:
  groups:
  - name: ai-paralegal.rules
    interval: 30s
    rules:
    - alert: HighErrorRate
      expr: rate(http_requests_total{job="ai-paralegal",status=~"5.."}[5m]) > 0.05
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "High error rate detected"
        description: "Error rate is above 5% for AI Paralegal service"
    
    - alert: HighResponseTime
      expr: histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{job="ai-paralegal"}[5m])) > 2
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "High response time detected"
        description: "95th percentile response time is above 2 seconds"
    
    - alert: PodDown
      expr: up{job="ai-paralegal"} == 0
      for: 1m
      labels:
        severity: critical
      annotations:
        summary: "AI Paralegal pod is down"
        description: "AI Paralegal service is not responding"
    
    - alert: HighMemoryUsage
      expr: container_memory_usage_bytes{pod=~"ai-paralegal-app-.*"} / container_spec_memory_limit_bytes > 0.8
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "High memory usage"
        description: "Memory usage is above 80% of limit"
EOF
    
    print_status "Alerts configured"
}

# Install Loki for log aggregation
install_loki() {
    print_step "Installing Loki for log aggregation..."
    
    # Add Grafana helm repo
    helm repo add grafana https://grafana.github.io/helm-charts
    helm repo update
    
    # Install Loki
    helm upgrade --install loki grafana/loki-stack \
        --namespace "$NAMESPACE" \
        --set loki.persistence.enabled=true \
        --set loki.persistence.storageClassName=local-path \
        --set loki.persistence.size=10Gi \
        --set promtail.enabled=true \
        --wait
    
    print_status "Loki installed successfully"
}

# Configure Grafana data sources
configure_grafana() {
    print_step "Configuring Grafana data sources..."
    
    # Wait for Grafana to be ready
    kubectl wait --for=condition=available --timeout=300s deployment/prometheus-grafana -n "$NAMESPACE"
    
    # Get Grafana admin password
    GRAFANA_PASS=$(kubectl get secret prometheus-grafana -n "$NAMESPACE" -o jsonpath="{.data.admin-password}" | base64 -d)
    
    print_status "Grafana admin password: $GRAFANA_PASS"
    print_status "Grafana URL: http://localhost:3000 (after port-forward)"
}

# Main installation
main() {
    print_status "Starting monitoring setup..."
    
    # Create namespace
    create_namespace
    
    # Install Prometheus
    install_prometheus
    
    # Install Loki
    read -p "Do you want to install Loki for log aggregation? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        install_loki
    fi
    
    # Create service monitor
    create_service_monitor
    
    # Create dashboards
    create_dashboards
    
    # Setup alerts
    setup_alerts
    
    # Configure Grafana
    configure_grafana
    
    print_status "Monitoring setup completed!"
    print_status ""
    print_status "Access points:"
    print_status "- Prometheus: kubectl port-forward -n $NAMESPACE svc/prometheus-kube-prometheus-prometheus 9090:9090"
    print_status "- Grafana: kubectl port-forward -n $NAMESPACE svc/prometheus-grafana 3000:80"
    print_status "- Alertmanager: kubectl port-forward -n $NAMESPACE svc/prometheus-kube-prometheus-alertmanager 9093:9093"
}

# Run main function
main