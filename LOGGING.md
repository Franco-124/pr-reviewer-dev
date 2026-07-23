# PR Review Agent — Logging Guide

This document describes the comprehensive logging system integrated into the PR Review Agent service.

## Overview

The application includes detailed, structured logging throughout the entire PR review pipeline to track execution, detect failures, and monitor success. Logs are written to both console (colorized for readability) and rotating log files.

## Log Levels

- **DEBUG**: Detailed diagnostic information (function entry/exit, API calls, internal state transitions)
- **INFO**: Key milestones and success events (webhook received, review complete, findings saved)
- **WARNING**: Potentially problematic situations (already-reviewed PR skipped, missing README, validation issues)
- **ERROR**: Error conditions that don't stop the service (failed API calls, temporary failures)
- **CRITICAL**: Service-breaking failures (startup failures, fatal exceptions)

## Log Locations

Logs are stored in the `logs/` directory at the project root:

```
logs/
├── pr_reviewer.log           # Main application log (rotated, max 10 MB, keeps 5 backups)
└── pr_reviewer_errors.log    # Error-level events only (same rotation policy)
```

Both files use a detailed format:
```
2026-07-23 14:32:15 | app.api.webhooks:45 | INFO | Processing PR: owner/repo#42 (id=123, sha=abc12345..., installation=456)
```

Console output is colorized for better readability:
- **DEBUG**: Cyan
- **INFO**: Green
- **WARNING**: Yellow
- **ERROR**: Red
- **CRITICAL**: Red background

## Execution Flow with Logging

### 1. **Service Startup** (app/main.py)

```
INFO  | Starting PR Review Agent service (v0.1.0)
DEBUG | Environment: LLM model=gpt-4, host=0.0.0.0:8000
INFO  | Initializing idempotency database...
INFO  | ✓ Idempotency database initialized successfully
INFO  | Initializing findings database...
INFO  | ✓ Findings database initialized successfully
INFO  | 🚀 PR Review Agent service started successfully
```

### 2. **Webhook Reception** (app/api/webhooks.py)

```
DEBUG | Received webhook request (payload size: 2450 bytes)
DEBUG | ✓ Webhook signature validation passed
INFO  | Received GitHub event: type=pull_request, action=opened
INFO  | Processing PR: owner/repo#15 (id=789, sha=def67890..., installation=123)
DEBUG | ✓ Background task scheduled for PR review
```

**If signature validation fails:**
```
WARNING | Webhook signature validation failed - rejecting request
```

**If event is ignored (e.g., non-PR or wrong action):**
```
INFO | Ignoring event: event_type=push, action=synchronize (not in {'opened', 'synchronize'})
```

### 3. **GitHub Authentication** (app/github/auth.py)

```
DEBUG | Loading GitHub App private key from file: ./github.pem
DEBUG | ✓ Private key loaded successfully (1704 bytes)
DEBUG | Generating GitHub App JWT (app_id=123456)
DEBUG | ✓ GitHub App JWT generated successfully
DEBUG | Exchanging App JWT for installation token (installation_id=456)
DEBUG | ✓ Installation token obtained (expires_at=2026-07-23T15:32:15Z)
```

**If private key is missing:**
```
ERROR | ✗ Private key file not found: ./github.pem
```

### 4. **Fetching PR Diff** (app/github/client.py)

```
DEBUG | Fetching files for owner/repo#PR15
DEBUG |   Fetching page 1 (per_page=100)
DEBUG |   Page 1: 8 files (total: 8)
INFO  | ✓ Fetched 8 files from owner/repo#PR15
DEBUG | Building unified diff for owner/repo#PR15
DEBUG |   Skipping binary_image.png (binary or oversized)
INFO  | ✓ Unified diff built: 7 files with patches, 1 skipped (binary/oversized), total size: 4521 bytes
```

### 5. **Review Pipeline** (app/agent/nodes.py)

#### Context Building:
```
DEBUG | [owner/repo] Building review context (fetching repository README)
INFO  | [owner/repo] ✓ Repository context enriched with README (3421 bytes)
```

Or, if README doesn't exist:
```
DEBUG | [owner/repo] Building review context (fetching repository README)
DEBUG | README.md not found for owner/repo at this ref
DEBUG | [owner/repo] No README found; proceeding with diff-only context
```

#### Security Review:
```
DEBUG | [owner/repo] Running Security review (draft + critique)
DEBUG | [owner/repo] Security: drafting findings...
DEBUG | [owner/repo] Security: draft complete (2 findings)
DEBUG | [owner/repo] Security: critiquing and refining...
INFO  | [owner/repo] ✓ Security review complete: 2 findings (approved=false)
```

#### Scalability, Style, Correctness Reviews (similar pattern):
```
INFO  | [owner/repo] ✓ Scalability review complete: 1 finding (approved=false)
INFO  | [owner/repo] ✓ Style review complete: 0 findings (approved=true)
INFO  | [owner/repo] ✓ Correctness review complete: 1 finding (approved=true)
```

#### Aggregation:
```
DEBUG | [owner/repo] Aggregating and ranking findings from all lenses
DEBUG | [owner/repo] Total findings collected: 4
DEBUG | [owner/repo] Finding breakdown: critical=1, warning=2, suggestion=1
DEBUG | [owner/repo] Checking for recurring findings...
DEBUG | [owner/repo] Finding classification: 4 new, 0 recurring
INFO  | [owner/repo] ✓ Aggregation complete: verdict=request_changes, readiness_score=47%
```

#### Output Formatting:
```
DEBUG | [owner/repo] Formatting review output for GitHub
INFO  | [owner/repo] ✓ Review output formatted: verdict=request_changes, body_length=2891, inline_comments=4
```

### 6. **Posting Review to GitHub** (app/github/client.py)

```
DEBUG | Posting review to owner/repo#PR15 (event=REQUEST_CHANGES, 4 inline comments)
INFO  | ✓ Review posted to GitHub: owner/repo#PR15 (review_id=5678910, event=REQUEST_CHANGES, 4 comments)
```

### 7. **Background Task Completion** (app/api/webhooks.py)

```
INFO  | [owner/repo#15] Starting PR review pipeline
DEBUG | [owner/repo#15] Checking idempotency (pr_id=789, sha=def67890...)
DEBUG | [owner/repo#15] Generating GitHub App installation token
DEBUG | [owner/repo#15] ✓ Installation token obtained
...
[review pipeline logs as above]
...
INFO  | [owner/repo#15] ✓ PR review complete and findings saved
```

**If idempotency check detects duplicate:**
```
INFO  | [owner/repo#15] ⊘ Skipping: PR already reviewed at this sha
```

**If anything fails:**
```
ERROR | [owner/repo#15] ✗ FAILED to process PR (sha=def67890...). Error type: HTTPStatusError, Message: 401 Unauthorized
```

Full exception traceback is included at ERROR level:
```
ERROR | [owner/repo#15] ✗ FAILED to process PR (sha=def67890...). Error type: KeyError, Message: 'token'
Traceback (most recent call last):
  File "app/api/webhooks.py", line 85, in process_pull_request
    token = await get_installation_token(...)
  ...
KeyError: 'token'
```

## Monitoring and Troubleshooting

### View Logs in Real-Time

While the service is running:

```bash
# Watch main log (colorized console output)
tail -f logs/pr_reviewer.log

# Watch error log
tail -f logs/pr_reviewer_errors.log

# Search for a specific PR
grep "owner/repo#15" logs/pr_reviewer.log

# Find failures
grep "✗" logs/pr_reviewer.log
grep "ERROR\|CRITICAL" logs/pr_reviewer.log
```

### Common Log Patterns to Watch For

#### **Success** (all green):
```
INFO  | [owner/repo#15] Starting PR review pipeline
...
INFO  | [owner/repo#15] ✓ PR review complete and findings saved
```

#### **Idempotency/Deduplication**:
```
INFO  | [owner/repo#15] ⊘ Skipping: PR already reviewed at this sha
```

#### **GitHub API Errors**:
```
ERROR | ✗ GitHub API error posting review: status=401, response=Bad credentials
```

Check: GitHub App ID, private key, or installation token expiry.

#### **LLM/OpenAI Errors**:
```
ERROR | [owner/repo#15] ✗ Security review failed: AuthenticationError: Invalid API key
```

Check: `OPENAI_API_KEY` environment variable.

#### **Database Errors**:
```
ERROR | [owner/repo#15] ✗ Aggregation failed: DatabaseError: table 'findings' doesn't exist
```

Check: Database initialization completed in startup logs.

#### **Signature Validation Failure**:
```
WARNING | Webhook signature validation failed - rejecting request
```

Check: `GITHUB_WEBHOOK_SECRET` matches GitHub app settings.

## Configuration

Logging behavior is defined in `app/logging_config.py`. To adjust:

1. **Log Level**: Change `level` in `LOGGING_CONFIG["loggers"]["app"]` from `DEBUG` to `INFO` for less verbosity.
2. **Log File Size**: Adjust `maxBytes` in the file handlers (default: 10 MB).
3. **Backup Count**: Change `backupCount` to keep more/fewer rotated logs.
4. **Console Output**: Disable `ColoredFormatter` in the `console` handler to remove colors.
5. **Third-Party Verbosity**: Adjust levels for `httpx`, `langchain`, etc., to reduce noise.

Example: To reduce verbosity to INFO in production:

```python
"loggers": {
    "app": {
        "level": "INFO",  # Changed from DEBUG
        ...
    }
}
```

## Log Analysis

### Example: Analyzing a Failed PR Review

**Step 1**: Search for the failed PR:
```bash
grep "owner/repo#15" logs/pr_reviewer.log | grep -E "ERROR|✗"
```

**Step 2**: Get the full execution timeline:
```bash
grep "owner/repo#15" logs/pr_reviewer.log
```

**Step 3**: Check for specific failure points:
```bash
grep -A 5 "owner/repo#15.*Failed\|owner/repo#15.*Error" logs/pr_reviewer.log
```

**Step 4**: Review the error log for stack traces:
```bash
grep "owner/repo#15" logs/pr_reviewer_errors.log
```

## Integration with Monitoring/Alerting

The logs can be parsed by external tools to trigger alerts on failures:

- **Error-level logs** → Page oncall
- **Failed PR review** (status code in log) → Slack notification
- **Repeated failures** (same PR, multiple times) → Bug ticket

Example Splunk query:
```
source="logs/pr_reviewer.log" "✗ FAILED" | stats count by owner, repo
```

Example alerting rule (Prometheus/Grafana):
```
increase(log_errors_total[5m]) > 10 → Page
```

## Security

- **Never log tokens or secrets**: Logs redact full tokens but may log partial versions for debugging (e.g., `sha=abc123...`).
- **Rotate old logs**: Automatic rotation removes 5+ backups (default 10 MB × 5 = 50 MB kept).
- **Access control**: Ensure `logs/` directory permissions are restrictive on production servers.

## Future Improvements

- Structured logging (JSON format) for log aggregation platforms (ELK, Datadog).
- Metrics export (review count, failure rate, average review time).
- Custom log context (request ID, trace ID) for cross-service correlation.
