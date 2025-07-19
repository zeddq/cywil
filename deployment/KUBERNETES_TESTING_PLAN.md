# Kubernetes Deployment Testing Plan for AI Paralegal POC

## Overview
This document defines comprehensive testing procedures for the AI Paralegal POC Kubernetes deployment. All tests should be executed sequentially to ensure system reliability, security, and performance.

## Pre-Testing Requirements

### 1. Environment Setup
- [ ] Verify kubectl access to remote cluster: `kubectl cluster-info`
- [ ] Confirm namespace exists: `kubectl get ns ai-paralegal`
- [ ] Check all pods are running: `kubectl get pods -n ai-paralegal`
- [ ] Verify storage provisioner: `kubectl get storageclass`

### 2. Security Prerequisites
- [ ] Update secrets.yaml with production credentials
- [ ] Verify no default passwords remain
- [ ] Confirm API keys are properly secured
- [ ] Enable TLS for ingress if not already configured

## Testing Phases

### Phase 1: Infrastructure Testing

#### 1.1 Cluster Health
```bash
# Test cluster connectivity
kubectl cluster-info
kubectl get nodes
kubectl top nodes

# Verify namespace resources
kubectl get all -n ai-paralegal
kubectl describe ns ai-paralegal
```

#### 1.2 Storage Testing
```bash
# Verify persistent volumes
kubectl get pv
kubectl get pvc -n ai-paralegal

# Test storage provisioning
kubectl apply -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: test-pvc
  namespace: ai-paralegal
spec:
  accessModes:
  - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
EOF

# Verify and cleanup
kubectl get pvc test-pvc -n ai-paralegal
kubectl delete pvc test-pvc -n ai-paralegal
```

#### 1.3 Network Connectivity
```bash
# Test service discovery
kubectl run test-pod --image=busybox -n ai-paralegal --rm -it -- sh
# Inside pod:
nslookup postgres-service
nslookup redis-service
nslookup qdrant-service
exit

# Test ingress
curl -H "Host: paralegal.local" http://<CLUSTER_IP>
```

### Phase 2: Database Testing

#### 2.1 PostgreSQL Testing
```bash
# Connect to PostgreSQL
kubectl exec -it -n ai-paralegal deployment/postgres -- psql -U paralegal -d paralegal

# Test queries
\dt
SELECT version();
SELECT current_database();
\q

# Test persistence
kubectl delete pod -n ai-paralegal -l app=postgres
kubectl wait --for=condition=ready pod -n ai-paralegal -l app=postgres
# Verify data still exists
```

#### 2.2 Redis Testing
```bash
# Connect to Redis
kubectl exec -it -n ai-paralegal deployment/redis -- redis-cli

# Test operations
PING
SET test:key "test-value"
GET test:key
DEL test:key
exit

# Test persistence
kubectl delete pod -n ai-paralegal -l app=redis
kubectl wait --for=condition=ready pod -n ai-paralegal -l app=redis
```

#### 2.3 Qdrant Testing
```bash
# Test Qdrant API
kubectl port-forward -n ai-paralegal svc/qdrant-service 6333:6333 &
PF_PID=$!

# Test collections
curl http://localhost:6333/collections
curl -X PUT http://localhost:6333/collections/test-collection \
  -H 'Content-Type: application/json' \
  -d '{
    "vectors": {
      "size": 768,
      "distance": "Cosine"
    }
  }'

# Cleanup
curl -X DELETE http://localhost:6333/collections/test-collection
kill $PF_PID
```

### Phase 3: Application Testing

#### 3.1 Health Checks
```bash
# Test liveness probe
kubectl exec -n ai-paralegal deployment/ai-paralegal -- curl -f http://localhost:8000/health

# Test readiness probe
kubectl exec -n ai-paralegal deployment/ai-paralegal -- curl -f http://localhost:8000/ready

# Monitor health check logs
kubectl logs -n ai-paralegal -l app=ai-paralegal --tail=50 | grep health
```

#### 3.2 API Endpoint Testing
```bash
# Port forward for local testing
kubectl port-forward -n ai-paralegal svc/ai-paralegal-service 8000:80 &
PF_PID=$!

# Test root endpoint
curl http://localhost:8000/

# Test API docs
curl http://localhost:8000/docs

# Test authentication (if enabled)
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "test", "password": "test"}'

# Cleanup
kill $PF_PID
```

#### 3.3 Core Functionality Testing
```bash
# Test statute search
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "termin przedawnienia",
    "code_type": "KC",
    "top_k": 5
  }'

# Test document generation
curl -X POST http://localhost:8000/api/v1/draft \
  -H "Content-Type: application/json" \
  -d '{
    "type": "pozew_upominawczy",
    "facts": {"amount": 45000, "date": "2025-04-22"},
    "goals": ["recover debt"]
  }'
```

### Phase 4: Performance Testing

#### 4.1 Resource Usage
```bash
# Monitor pod resources
kubectl top pods -n ai-paralegal
kubectl describe pod -n ai-paralegal -l app=ai-paralegal

# Check resource limits
kubectl get pods -n ai-paralegal -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.containers[*].resources}{"\n"}{end}'
```

#### 4.2 Load Testing
```bash
# Simple concurrent request test
for i in {1..10}; do
  curl -X POST http://localhost:8000/api/v1/search \
    -H "Content-Type: application/json" \
    -d '{"query": "test query", "top_k": 5}' &
done
wait

# Monitor response times
kubectl logs -n ai-paralegal -l app=ai-paralegal --tail=100 | grep "response_time"
```

#### 4.3 Scaling Testing
```bash
# Test horizontal scaling
kubectl scale deployment/ai-paralegal -n ai-paralegal --replicas=3
kubectl wait --for=condition=ready pod -n ai-paralegal -l app=ai-paralegal

# Verify load distribution
for i in {1..20}; do
  kubectl exec -n ai-paralegal deployment/ai-paralegal -- hostname
done | sort | uniq -c

# Scale back
kubectl scale deployment/ai-paralegal -n ai-paralegal --replicas=1
```

### Phase 5: Security Testing

#### 5.1 Secret Management
```bash
# Verify secrets are not exposed
kubectl get secret -n ai-paralegal openai-secret -o yaml | grep -v "data:"
kubectl exec -n ai-paralegal deployment/ai-paralegal -- printenv | grep -i secret
kubectl exec -n ai-paralegal deployment/ai-paralegal -- printenv | grep -i api_key
```

#### 5.2 Network Policies
```bash
# Test pod-to-pod communication
kubectl run test-client --image=busybox -n ai-paralegal --rm -it -- sh
# Inside pod:
wget -O- http://ai-paralegal-service/health
wget -O- http://postgres-service:5432  # Should fail if network policies are correct
exit
```

#### 5.3 RBAC Testing
```bash
# Verify service account permissions
kubectl auth can-i --list --as=system:serviceaccount:ai-paralegal:default -n ai-paralegal
```

### Phase 6: Reliability Testing

#### 6.1 Failure Recovery
```bash
# Test pod recovery
kubectl delete pod -n ai-paralegal -l app=ai-paralegal
kubectl wait --for=condition=ready pod -n ai-paralegal -l app=ai-paralegal --timeout=120s

# Test node failure simulation (if multi-node)
kubectl drain <node-name> --ignore-daemonsets
kubectl uncordon <node-name>
```

#### 6.2 Backup and Restore
```bash
# Test backup script
./deployment/scripts/cluster-management.sh backup

# Verify backup exists
ls -la /tmp/ai-paralegal-backup-*

# Test restore (in test namespace)
kubectl create ns ai-paralegal-test
./deployment/scripts/cluster-management.sh restore -n ai-paralegal-test
kubectl delete ns ai-paralegal-test
```

#### 6.3 Rolling Updates
```bash
# Trigger rolling update
kubectl set env deployment/ai-paralegal -n ai-paralegal TEST_UPDATE="$(date)"
kubectl rollout status deployment/ai-paralegal -n ai-paralegal

# Verify zero-downtime
while true; do
  curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/health
  sleep 1
done
```

### Phase 7: Monitoring Testing

#### 7.1 Metrics Collection
```bash
# If monitoring is enabled
kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 9090:9090 &
curl http://localhost:9090/api/v1/query?query=up

# Check application metrics
curl http://localhost:9090/api/v1/query?query=http_requests_total
```

#### 7.2 Log Aggregation
```bash
# Check log output
kubectl logs -n ai-paralegal -l app=ai-paralegal --tail=100
kubectl logs -n ai-paralegal -l app=postgres --tail=50
kubectl logs -n ai-paralegal -l app=redis --tail=50
kubectl logs -n ai-paralegal -l app=qdrant --tail=50

# Test log rotation
kubectl exec -n ai-paralegal deployment/ai-paralegal -- ls -la /tmp/
```

### Phase 8: Integration Testing

#### 8.1 End-to-End Workflow
```bash
# Full workflow test
# 1. Search for statute
SEARCH_RESULT=$(curl -s -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "termin przedawnienia", "code_type": "KC", "top_k": 3}')

# 2. Generate document based on search
curl -X POST http://localhost:8000/api/v1/draft \
  -H "Content-Type: application/json" \
  -d "{
    \"type\": \"pozew_upominawczy\",
    \"facts\": {\"amount\": 45000, \"date\": \"2025-04-22\"},
    \"context\": $SEARCH_RESULT
  }"

# 3. Validate the generated document
# (Add validation endpoint test when available)
```

#### 8.2 Database Integration
```bash
# Verify all databases are accessible from app
kubectl exec -n ai-paralegal deployment/ai-paralegal -- python -c "
import asyncio
import asyncpg
import redis
from qdrant_client import AsyncQdrantClient

async def test():
    # Test PostgreSQL
    pg_conn = await asyncpg.connect('postgresql://paralegal:paralegal@postgres-service/paralegal')
    print('PostgreSQL: Connected')
    await pg_conn.close()
    
    # Test Redis
    r = redis.Redis(host='redis-service', port=6379)
    r.ping()
    print('Redis: Connected')
    
    # Test Qdrant
    client = AsyncQdrantClient(host='qdrant-service', port=6333)
    collections = await client.get_collections()
    print(f'Qdrant: Connected, {len(collections.collections)} collections')

asyncio.run(test())
"
```

## Post-Testing Actions

### 1. Performance Baseline
- [ ] Document response times for key operations
- [ ] Record resource usage under normal load
- [ ] Set up alerts based on baseline metrics

### 2. Security Hardening
- [ ] Rotate all secrets used during testing
- [ ] Enable network policies
- [ ] Configure pod security policies
- [ ] Set up audit logging

### 3. Documentation Updates
- [ ] Update deployment README with test results
- [ ] Document any issues found and resolutions
- [ ] Create runbook for common operations
- [ ] Update architecture diagrams if needed

## Continuous Testing

### Daily Tests
```bash
# Health check automation
kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: CronJob
metadata:
  name: daily-health-check
  namespace: ai-paralegal
spec:
  schedule: "0 2 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: health-check
            image: curlimages/curl:latest
            command:
            - /bin/sh
            - -c
            - |
              curl -f http://ai-paralegal-service/health || exit 1
              curl -f http://postgres-service:5432 || exit 1
              curl -f http://redis-service:6379/ping || exit 1
              curl -f http://qdrant-service:6333/collections || exit 1
          restartPolicy: OnFailure
EOF
```

### Weekly Tests
- Full backup and restore test
- Performance regression testing
- Security scan with tools like kube-bench

### Monthly Tests
- Disaster recovery drill
- Full cluster upgrade test (in staging)
- Penetration testing

## Testing Commands Quick Reference

```bash
# Quick health check
./deployment/scripts/cluster-management.sh health

# View logs
./deployment/scripts/cluster-management.sh logs app

# Debug pod
./deployment/scripts/cluster-management.sh debug app

# Full status check
./deployment/scripts/cluster-management.sh status

# Performance monitoring
watch -n 2 'kubectl top pods -n ai-paralegal'
```

## Success Criteria

All tests pass when:
1. ✅ All pods are running and healthy
2. ✅ All endpoints respond within 2 seconds
3. ✅ No errors in logs for 30 minutes
4. ✅ Resource usage stays under 80% of limits
5. ✅ All security tests pass
6. ✅ Backup and restore completes successfully
7. ✅ Zero-downtime deployment verified

## Troubleshooting Guide

### Common Issues

1. **Pod CrashLoopBackOff**
   - Check logs: `kubectl logs -p -n ai-paralegal <pod-name>`
   - Verify secrets: `kubectl get secrets -n ai-paralegal`
   - Check resource limits

2. **Database Connection Errors**
   - Verify service DNS: `kubectl exec -n ai-paralegal <pod> -- nslookup postgres-service`
   - Check credentials in secrets
   - Verify PVC is bound

3. **Ingress Not Working**
   - Check ingress controller: `kubectl get pods -n kube-system | grep traefik`
   - Verify DNS resolution
   - Check ingress rules: `kubectl describe ingress -n ai-paralegal`

4. **Performance Issues**
   - Check resource usage: `kubectl top pods -n ai-paralegal`
   - Review slow query logs in PostgreSQL
   - Check Qdrant index optimization

## Notes

- Always test in staging before production
- Keep test data separate from production data
- Monitor test execution for anomalies
- Document any deviations from expected behavior
- Review and update tests quarterly