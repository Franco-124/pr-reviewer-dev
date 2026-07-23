# Logging Quick Reference

## View Logs

```bash
# Follow main log in real-time (colorized)
tail -f logs/pr_reviewer.log

# Follow error log
tail -f logs/pr_reviewer_errors.log

# View last 50 lines
tail -50 logs/pr_reviewer.log
```

## Search Logs

```bash
# Find a specific PR
grep "owner/repo#42" logs/pr_reviewer.log

# Find all failures
grep "✗" logs/pr_reviewer.log

# Find all successes
grep "✓" logs/pr_reviewer.log

# Find all errors
grep "ERROR\|CRITICAL" logs/pr_reviewer.log

# Find warnings
grep "WARNING" logs/pr_reviewer.log

# Find a specific phase (e.g., all GitHub API calls)
grep "GitHub API\|post_review\|fetch_diff" logs/pr_reviewer.log
```

## Log Patterns

### ✅ Successful PR Review
```
INFO  | [owner/repo#15] Starting PR review pipeline
DEBUG | [owner/repo#15] Checking idempotency
...
INFO  | [owner/repo#15] ✓ PR review complete and findings saved
```

### ⚠️ Already Reviewed
```
INFO  | [owner/repo#15] ⊘ Skipping: PR already reviewed at this sha
```

### ❌ Authentication Failure
```
ERROR | ✗ GitHub API error exchanging JWT for token: status=401
```

### ❌ Signature Validation Failed
```
WARNING | Webhook signature validation failed - rejecting request
```

### ❌ LLM/OpenAI Error
```
ERROR | [owner/repo#15] ✗ Security review failed: AuthenticationError: Invalid API key
```

### 📊 Metrics in Logs
- File counts: `7 files with patches, 1 skipped (binary/oversized)`
- Finding breakdown: `critical=1, warning=2, suggestion=1`
- Review verdict: `verdict=request_changes, readiness_score=47%`
- Inline comments: `{len(comments)} comments`

## Startup Verification

Service should print:
```
INFO  | 🚀 PR Review Agent service started successfully
INFO  | ✓ Idempotency database initialized successfully
INFO  | ✓ Findings database initialized successfully
```

If you see errors here, check:
- Database files exist and are accessible
- Environment variables set correctly
- Required dependencies installed

## Troubleshooting

| Issue | What to Check |
|-------|---------------|
| No logs appearing | Check `logs/` directory exists; ensure service is running |
| "Signature validation failed" | Verify `GITHUB_WEBHOOK_SECRET` matches GitHub app settings |
| "Invalid API key" | Check `OPENAI_API_KEY` environment variable |
| "401 Unauthorized" | Check GitHub App ID, private key file, or token expiry |
| "Table doesn't exist" | Review database initialization logs at startup |
| "Skipping already-reviewed PR" | This is normal; PR was processed on a prior push |

## Log Locations

```
logs/
├── pr_reviewer.log          # Main log — all INFO and above
└── pr_reviewer_errors.log   # Errors only — ERROR and above
```

Both rotate at 10 MB, keeping 5 backups.

## Adjusting Verbosity

**For less noise (production)**:
Edit `app/logging_config.py`:
```python
"loggers": {
    "app": {
        "level": "INFO",  # Change from DEBUG
        ...
    }
}
```

**For more detail (debugging)**:
```python
"loggers": {
    "app": {
        "level": "DEBUG",  # Keep as is
        ...
    },
    # Also reduce third-party noise:
    "httpx": {
        "level": "DEBUG",  # Change from INFO
        ...
    }
}
```

## Parsing Logs Programmatically

All log lines follow this format:
```
TIMESTAMP | MODULE:LINE | LEVEL | MESSAGE
```

Example:
```
2026-07-23 14:32:15 | app.api.webhooks:45 | INFO | Processing PR: owner/repo#42 (id=123, sha=abc12345..., installation=456)
```

Use regex to extract PR info:
```bash
grep -oP '\[.*?#\K\d+' logs/pr_reviewer.log
```

## Alerting Rules

Set up alerts for:
```bash
# Critical failures
grep "✗ FAILED\|✗ GitHub API error" logs/pr_reviewer.log

# Any errors
grep "ERROR" logs/pr_reviewer.log

# Auth failures
grep "Invalid signature\|401\|403\|Invalid API key" logs/pr_reviewer.log
```

Example monitoring query (Splunk):
```
source="logs/pr_reviewer.log" "✗" | stats count by error_type
```
