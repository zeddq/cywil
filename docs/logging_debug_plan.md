# Logging Correlation-ID Debug Plan

## 1. Issue Summary
Correlation IDs (`correlation_id`) are missing from log lines produced by Uvicorn **and** application modules after the recent refactor to the new central logging manager.  The formatter/filter chain is configured, but records propagated by Uvicorn’s loggers never receive the custom attribute, so the placeholder appears empty in the output.

---

## 2. Key Implementation Files

| Area | File |
|------|------|
| Log config dict  | `app/logging_config.py` |
| Context helpers  | `app/core/logging_utils.py` |
| Logger bootstrap | `app/core/logger_manager.py` |
| API entrypoint   | `app/main.py` |
| Container entry  | `run.py` |
| Runtime command  | `docker-compose.yml` |

---

## 3. Debug / Fix Steps

1. **Re-enable filter globally**  
   • Ensure `CorrelationIdFilter` is attached to **all** console handlers regardless of JSON mode.  
   • Fixed in `logging_config.py` – both `default` & `access` handlers now include `filters: ["correlation_id"]`.

2. **Verify formatter picks it up**  
   • `StructuredFormatter` already falls back to `record.correlation_id`.

3. **Single bootstrap path**  
   • `run.py` → `configure_logging()` (dictConfig) → **done before** `uvicorn.run()`.

4. **Smoke test**  
   ```bash
   LOG_LEVEL=DEBUG LOG_FORMAT=json docker-compose up api
   ```
   Expect each log line to include e.g.:
   ```json
   {"timestamp":"…","level":"INFO","logger":"uvicorn","message":"Started server","correlation_id":"no-correlation-id"}
   ```

5. **End-to-end request**  
   ```bash
   curl -H "X-User-ID: test" http://localhost:8000/health
   ```
   • Response headers should include `X-Correlation-ID`.  
   • Corresponding access log line contains the same ID.

---

## 4. Expected Validation Output (excerpt)
```
api_1  | 2024-07-16T10:45:01Z INFO  uvicorn  {"correlation_id":"no-correlation-id", …, "message":"Uvicorn running on http://0.0.0.0:8000"}
api_1  | 2024-07-16T10:45:03Z INFO  app.main {"correlation_id":"e483…", "event":"api_request_start", "path":"/health"}
api_1  | 2024-07-16T10:45:03Z INFO  uvicorn.access {"correlation_id":"e483…", "client_addr":"127.0.0.1","status_code":200}
```
If the IDs appear **and** are consistent within a single request, the issue is resolved. 
