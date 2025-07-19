# AI Paralegal Operations Runbook

## Table of Contents

1. [System Overview](#system-overview)
2. [Daily Operations](#daily-operations)
3. [Monitoring](#monitoring)
4. [Incident Response](#incident-response)
5. [Common Procedures](#common-procedures)
6. [Troubleshooting Guide](#troubleshooting-guide)
7. [Disaster Recovery](#disaster-recovery)
8. [Security Operations](#security-operations)

## System Overview

### Architecture Components

- **Application**: FastAPI-based Python application
- **Database**: PostgreSQL 14
- **Cache**: Redis 7
- **Vector DB**: Qdrant 1.7
- **AI Provider**: OpenAI API
- **Infrastructure**: Docker/Kubernetes

### Critical Services

| Service | Purpose | SLA |
|---------|---------|-----|
| API Gateway | Request handling | 99.9% |
| PostgreSQL | Data persistence | 99.9% |
| Redis | Caching & state | 99.5% |
| Qdrant | Vector search | 99.5% |

## Daily Operations

### Morning Checklist (9:00 AM)

```bash
#!/bin/bash
# Daily health check script

echo "=== AI Paralegal Daily Health Check ==="
echo "Date: $(date)"

# 1. Check service status
echo -e "\n1. Service Status:"
docker-compose ps

# 2. Check API health
echo -e "\n2. API Health:"
curl -s http://localhost:8000/health | jq .

# 3. Check database connections
echo -e "\n3. Database Connections:"
docker exec paralegal-postgres psql -U paralegal_user -c "SELECT count(*) FROM pg_stat_activity;"

# 4. Check Redis status
echo -e "\n4. Redis Status:"
docker exec paralegal-redis redis-cli INFO server | grep uptime

# 5. Check disk usage
echo -e "\n5. Disk Usage:"
df -h | grep -E "Filesystem|docker"

# 6. Check logs for errors
echo -e "\n6. Recent Errors (last hour):"
docker-compose logs --since 1h app | grep -E "ERROR|CRITICAL" | tail -10
```

### Evening Checklist (6:00 PM)

1. Review daily metrics
2. Check backup completion
3. Verify log rotation
4. Review security alerts

## Monitoring

### Key Metrics to Monitor

#### Application Metrics

```python
# Critical metrics thresholds
METRICS_THRESHOLDS = {
    "request_latency_p95": 1000,  # ms
    "error_rate": 0.01,  # 1%
    "circuit_breaker_open": 0,
    "cache_hit_rate": 0.8,  # 80%
}
```

#### System Metrics

| Metric | Warning | Critical |
|--------|---------|----------|
| CPU Usage | 70% | 85% |
| Memory Usage | 80% | 90% |
| Disk Usage | 75% | 85% |
| DB Connections | 80% | 90% |

### Monitoring Commands

```bash
# Real-time metrics
watch -n 5 'curl -s http://localhost:8000/metrics | jq .'

# Database performance
docker exec paralegal-postgres psql -U paralegal_user -c "
SELECT query, calls, mean_exec_time 
FROM pg_stat_statements 
WHERE mean_exec_time > 1000 
ORDER BY mean_exec_time DESC 
LIMIT 10;"

# Redis memory usage
docker exec paralegal-redis redis-cli INFO memory

# Container resources
docker stats --no-stream
```

### Grafana Dashboards

1. **Overview Dashboard**
   - Request rate
   - Error rate
   - Response time
   - Active users

2. **Service Health Dashboard**
   - Circuit breaker states
   - Tool execution metrics
   - Cache performance
   - Database connections

3. **Infrastructure Dashboard**
   - CPU/Memory usage
   - Disk I/O
   - Network traffic
   - Container health

## Incident Response

### Severity Levels

| Level | Description | Response Time | Example |
|-------|-------------|---------------|---------|
| P1 | Service Down | 15 min | API not responding |
| P2 | Major Degradation | 30 min | >50% errors |
| P3 | Minor Issue | 2 hours | Slow queries |
| P4 | Low Priority | 24 hours | UI bug |

### Incident Response Procedure

1. **Identify**
   ```bash
   # Quick health check
   ./scripts/health_check.sh
   
   # Check recent logs
   docker-compose logs --tail 100 app | grep ERROR
   ```

2. **Triage**
   - Determine severity
   - Check monitoring dashboards
   - Review error logs

3. **Communicate**
   - Update status page
   - Notify stakeholders
   - Create incident ticket

4. **Mitigate**
   - Apply immediate fix
   - Scale resources if needed
   - Enable circuit breakers

5. **Resolve**
   - Deploy permanent fix
   - Verify resolution
   - Update documentation

6. **Post-Mortem**
   - Root cause analysis
   - Timeline of events
   - Action items

### Common Incident Responses

#### High Error Rate

```bash
# 1. Check circuit breaker status
curl http://localhost:8000/metrics | jq '.tools.circuit_states'

# 2. Reset circuit breakers if needed
curl -X POST http://localhost:8000/admin/reset-circuit/search_statute

# 3. Check OpenAI API status
curl https://status.openai.com/api/v2/status.json

# 4. Scale up if needed
docker-compose scale app=4
```

#### Database Connection Issues

```bash
# 1. Check connection pool
docker exec paralegal-postgres psql -U paralegal_user -c "
SELECT state, count(*) 
FROM pg_stat_activity 
GROUP BY state;"

# 2. Kill idle connections
docker exec paralegal-postgres psql -U paralegal_user -c "
SELECT pg_terminate_backend(pid) 
FROM pg_stat_activity 
WHERE state = 'idle' 
AND state_change < NOW() - INTERVAL '10 minutes';"

# 3. Restart connection pool
docker-compose restart app
```

#### Memory Issues

```bash
# 1. Check memory usage
docker stats --no-stream

# 2. Clear Redis cache if needed
docker exec paralegal-redis redis-cli FLUSHDB

# 3. Restart with increased memory
docker-compose down
docker-compose up -d --scale app=2
```

## Common Procedures

### Deploying Updates

```bash
#!/bin/bash
# Deployment script

# 1. Backup database
./scripts/backup_db.sh

# 2. Pull latest code
git pull origin main

# 3. Build new image
docker-compose build app

# 4. Rolling update
docker-compose up -d --no-deps --scale app=2 app
sleep 30
docker-compose up -d --no-deps app

# 5. Run migrations
docker-compose exec app alembic upgrade head

# 6. Verify deployment
curl http://localhost:8000/health
```

### Database Maintenance

```bash
# Weekly maintenance
docker exec paralegal-postgres vacuumdb -U paralegal_user -d paralegal_prod -z

# Reindex tables
docker exec paralegal-postgres psql -U paralegal_user -c "REINDEX DATABASE paralegal_prod;"

# Update statistics
docker exec paralegal-postgres psql -U paralegal_user -c "ANALYZE;"
```

### Log Management

```bash
# Rotate logs
docker-compose logs app > logs/app_$(date +%Y%m%d).log
docker-compose logs --tail 0 -f app > logs/app_current.log &

# Archive old logs
find logs/ -name "*.log" -mtime +30 -exec gzip {} \;
find logs/ -name "*.gz" -mtime +90 -delete

# Search logs
grep -r "ERROR.*search_statute" logs/ | tail -20
```

### Cache Management

```python
# Clear specific cache entries
import asyncio
from app.core.performance_utils import query_cache, embedding_cache

async def clear_caches():
    # Clear all query cache
    await query_cache.clear()
    
    # Clear embedding cache
    await embedding_cache.clear()
    
    print("Caches cleared")

asyncio.run(clear_caches())
```

## Troubleshooting Guide

### Diagnostic Tools

```python
# diagnostics.py
import asyncio
from app.services import initialize_services

async def run_diagnostics():
    print("=== System Diagnostics ===")
    
    # Initialize services
    lifecycle = initialize_services()
    await lifecycle.startup()
    
    # Check health
    health = await lifecycle.check_health()
    print(f"\nOverall Health: {'✓' if health['healthy'] else '✗'}")
    
    for service in health['services']:
        status = '✓' if service['status'] == 'healthy' else '✗'
        print(f"{status} {service['name']}: {service['message']}")
    
    await lifecycle.shutdown()

asyncio.run(run_diagnostics())
```

### Common Issues and Solutions

#### Issue: Slow Response Times

**Symptoms**: P95 latency > 2s

**Diagnosis**:
```bash
# Check slow queries
docker exec paralegal-postgres psql -U paralegal_user -c "
SELECT query, mean_exec_time, calls 
FROM pg_stat_statements 
WHERE mean_exec_time > 500 
ORDER BY mean_exec_time DESC;"

# Check cache hit rate
curl http://localhost:8000/metrics | jq '.tools.aggregate_metrics'
```

**Solution**:
1. Optimize slow queries
2. Increase cache TTL
3. Add database indexes
4. Scale horizontally

#### Issue: Circuit Breaker Open

**Symptoms**: ServiceUnavailableError

**Diagnosis**:
```bash
# Check circuit states
curl http://localhost:8000/metrics | jq '.tools | {
  tool: .tool,
  state: .state,
  failures: .metrics.failed_calls
}'
```

**Solution**:
1. Check external service status
2. Review error logs
3. Adjust circuit breaker thresholds
4. Manual reset if needed

#### Issue: Memory Leak

**Symptoms**: Gradual memory increase

**Diagnosis**:
```python
# memory_profile.py
import tracemalloc
import asyncio
from app.orchestrator_refactored import RefactoredParalegalAgent

tracemalloc.start()

async def profile_memory():
    agent = RefactoredParalegalAgent()
    await agent.initialize()
    
    # Run some operations
    for i in range(100):
        await agent.process_message_stream("Test message")
    
    # Get memory usage
    current, peak = tracemalloc.get_traced_memory()
    print(f"Current: {current / 1024 / 1024:.2f} MB")
    print(f"Peak: {peak / 1024 / 1024:.2f} MB")
    
    await agent.shutdown()

asyncio.run(profile_memory())
```

**Solution**:
1. Review code for circular references
2. Check cache sizes
3. Implement proper cleanup
4. Use memory profiler

## Disaster Recovery

### Backup Strategy

#### Daily Backups
```bash
#!/bin/bash
# backup.sh
DATE=$(date +%Y%m%d_%H%M%S)

# Database backup
docker exec paralegal-postgres pg_dump -U paralegal_user paralegal_prod | gzip > backups/db_$DATE.sql.gz

# Redis backup
docker exec paralegal-redis redis-cli BGSAVE
docker cp paralegal-redis:/data/dump.rdb backups/redis_$DATE.rdb

# Qdrant backup
curl -X POST http://localhost:6333/collections/statutes_prod/snapshots

# Upload to S3
aws s3 sync backups/ s3://paralegal-backups/$(date +%Y/%m/%d)/
```

### Recovery Procedures

#### Database Recovery
```bash
# 1. Stop application
docker-compose stop app

# 2. Restore database
gunzip -c backups/db_20240115_120000.sql.gz | \
  docker exec -i paralegal-postgres psql -U paralegal_user paralegal_prod

# 3. Verify restoration
docker exec paralegal-postgres psql -U paralegal_user -c "SELECT COUNT(*) FROM cases;"

# 4. Restart application
docker-compose start app
```

#### Full System Recovery
```bash
# 1. Provision new infrastructure
terraform apply

# 2. Restore data
./scripts/restore_all.sh 2024-01-15

# 3. Verify services
./scripts/health_check.sh

# 4. Update DNS
./scripts/update_dns.sh
```

### RTO/RPO Targets

| Component | RTO | RPO |
|-----------|-----|-----|
| API | 30 min | 0 min |
| Database | 1 hour | 1 hour |
| Cache | 15 min | N/A |
| Vector DB | 2 hours | 24 hours |

## Security Operations

### Security Checklist

#### Daily
- [ ] Review authentication logs
- [ ] Check for failed login attempts
- [ ] Monitor API rate limits
- [ ] Review error logs for security issues

#### Weekly
- [ ] Run vulnerability scanner
- [ ] Review access logs
- [ ] Update dependencies
- [ ] Rotate API keys

#### Monthly
- [ ] Security audit
- [ ] Penetration testing
- [ ] Update SSL certificates
- [ ] Review user permissions

### Security Commands

```bash
# Check for suspicious activity
docker-compose logs app | grep -E "401|403|429" | tail -50

# Review user activity
docker exec paralegal-postgres psql -U paralegal_user -c "
SELECT user_id, COUNT(*) as requests, 
       COUNT(DISTINCT DATE(created_at)) as active_days
FROM response_history 
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY user_id 
ORDER BY requests DESC;"

# Check SSL certificate expiry
echo | openssl s_client -servername your-domain.com -connect your-domain.com:443 2>/dev/null | openssl x509 -noout -dates
```

### Incident Response Plan

1. **Detection**
   - Monitor security alerts
   - Review anomaly reports
   - Check threat intelligence

2. **Containment**
   - Isolate affected systems
   - Block suspicious IPs
   - Disable compromised accounts

3. **Eradication**
   - Remove malicious code
   - Patch vulnerabilities
   - Update security rules

4. **Recovery**
   - Restore from clean backups
   - Verify system integrity
   - Resume normal operations

5. **Lessons Learned**
   - Document incident
   - Update procedures
   - Implement preventive measures

## Appendix

### Useful Scripts

#### Health Check API
```python
# health_check_api.py
import httpx
import asyncio

async def comprehensive_health_check():
    async with httpx.AsyncClient() as client:
        # Check main API
        api_health = await client.get("http://localhost:8000/health")
        
        # Check specific endpoints
        endpoints = ["/metrics", "/"]
        
        results = {
            "api_health": api_health.json(),
            "endpoints": {}
        }
        
        for endpoint in endpoints:
            try:
                resp = await client.get(f"http://localhost:8000{endpoint}")
                results["endpoints"][endpoint] = resp.status_code
            except Exception as e:
                results["endpoints"][endpoint] = str(e)
        
        return results

print(asyncio.run(comprehensive_health_check()))
```

#### Performance Test
```python
# perf_test.py
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
import httpx

async def load_test(num_requests=100, concurrent=10):
    url = "http://localhost:8000/chat"
    headers = {"X-User-ID": "load-test"}
    
    async def make_request(session, i):
        start = time.time()
        data = {"message": f"Test message {i}"}
        
        try:
            resp = await session.post(url, json=data, headers=headers)
            return time.time() - start, resp.status_code
        except Exception as e:
            return time.time() - start, str(e)
    
    async with httpx.AsyncClient() as client:
        tasks = []
        for i in range(num_requests):
            if len(tasks) >= concurrent:
                done, tasks = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                tasks = list(tasks)
            
            tasks.append(asyncio.create_task(make_request(client, i)))
        
        results = await asyncio.gather(*tasks)
    
    # Analysis
    durations = [r[0] for r in results if isinstance(r[1], int)]
    errors = [r for r in results if not isinstance(r[1], int)]
    
    print(f"Total requests: {num_requests}")
    print(f"Successful: {len(durations)}")
    print(f"Failed: {len(errors)}")
    print(f"Avg response time: {sum(durations)/len(durations):.3f}s")
    print(f"Min response time: {min(durations):.3f}s")
    print(f"Max response time: {max(durations):.3f}s")

asyncio.run(load_test())
```

### Emergency Contacts

| Role | Contact | When to Call |
|------|---------|--------------|
| On-Call Engineer | +48 XXX XXX XXX | P1/P2 incidents |
| DevOps Lead | devops@company.com | Infrastructure issues |
| Security Team | security@company.com | Security incidents |
| OpenAI Support | support@openai.com | API issues |