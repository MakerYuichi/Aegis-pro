-- Seed 11 demo incidents for the Acme fictional dataset.
--
-- Runs on fresh Postgres volume (mounted at /docker-entrypoint-initdb.d).
-- Re-run safe: the leading DELETE wipes only incidents tagged demo_seed.
--
-- Embeddings are left NULL — src/demo/seed_backfill.py fills them on
-- startup when DEMO_MODE=true. SQL cannot call all-MiniLM-L6-v2.
-- tests/test_demo_seed.py fails the build if you do.

-- Idempotent re-run: clear previous seed, keep everything else.
DELETE FROM incidents WHERE extra_metadata->>'demo_seed' = 'true';

INSERT INTO incidents (
    incident_id, service_name, severity, status, title, description,
    stack_trace, exception_type, file_path, line_number,
    root_cause, suggested_fix, rollback_command, confidence_score,
    declared_at, extra_metadata, affected_services
) VALUES

-- ── 1. payment-api — P0 — ACTIVE ──────────────────────────────
(
  'INC-20260916-A3F2B1',
  'payment-api',
  'P0',
  'active',
  'UPI Payment Failure — Null Pointer in Reference Resolution',
  'Elevated UPI payment failures since the 14:22 deploy. All failing requests share the same stack signature.',
  'java.lang.NullPointerException: Cannot invoke "String.length()" because the return value of "com.acme.payment.UpiResponse.getReferenceId()" is null
	at com.acme.payment.PaymentProcessor.processUpiPayment(PaymentProcessor.java:442)
	at com.acme.payment.PaymentController.handle(PaymentController.java:118)',
  'NullPointerException',
  'src/main/java/com/acme/payment/PaymentProcessor.java',
  442,
  'PR #127 removed the null guard on upiResponse.getReferenceId() during a refactor of the UPI response handling path. UPI gateways intermittently return a response without a reference id on failure.',
  'Restore the null guard before accessing getReferenceId(). Fall back to request.getTransactionId() when the gateway omits the reference.',
  'kubectl rollout undo deploy/payment-api -n production',
  0.95,
  NOW() - INTERVAL '4 hours',
  '{
    "demo_seed": true,
    "github": {
      "blame": {
        "commit_hash": "a3f9d21c",
        "author": "@prisha",
        "author_avatar": null,
        "message": "refactor(upi): simplify response handling",
        "line": 442,
        "file": "src/main/java/com/acme/payment/PaymentProcessor.java",
        "pr_number": 127,
        "pr_title": "refactor(upi): simplify response handling",
        "pr_url": "https://github.com/acme-demo/payment-service/pull/127",
        "pr_author": "@prisha",
        "contributors": [
          {"username": "@prisha", "role": "author", "avatar": null, "url": null},
          {"username": "@marcus", "role": "reviewer", "avatar": null, "url": null}
        ]
      },
      "related_prs": [
        {
          "number": 127,
          "title": "refactor(upi): simplify response handling",
          "author": "@prisha",
          "url": "https://github.com/acme-demo/payment-service/pull/127",
          "merged_at": "2026-09-14T18:32:00Z",
          "files": ["src/main/java/com/acme/payment/PaymentProcessor.java"],
          "relevance_score": 0.93,
          "reason": "PR #127 removed the null guard on upiResponse.getReferenceId() at line 442."
        },
        {
          "number": 125,
          "title": "feat(ledger): add idempotency key to entries",
          "author": "@sofia",
          "url": "https://github.com/acme-demo/payment-service/pull/125",
          "merged_at": "2026-09-12T09:21:00Z",
          "files": ["src/main/java/com/acme/ledger/LedgerEntry.java"],
          "relevance_score": 0.41,
          "reason": "PR #125 touched LedgerEntry, not the reference-id path."
        }
      ]
    },
    "code_context": {
      "file_path": "src/main/java/com/acme/payment/PaymentProcessor.java",
      "line_number": 442,
      "total_lines": 612,
      "code_snippet": " 435  UpiResponse upiResponse = upiGateway.initiate(request);\n 436\n 437  LedgerEntry entry = new LedgerEntry();\n 438  entry.setAmount(request.getAmount());\n 439  entry.setCurrency(request.getCurrency());\n 440\n 441\n 442 >>>  entry.setReference(upiResponse.getReferenceId());\n 443\n 444  ledgerClient.record(entry);",
      "simulated": true
    }
  }'::jsonb,
  '["payment-api", "auth", "ledger", "fraud"]'::jsonb
),

-- ── 2. payment-api — P0 — ACTIVE ──────────────────────────────
(
  'INC-20260916-B7C1E9',
  'payment-api',
  'P0',
  'active',
  'Payment Reconciliation Mismatch After Deploy',
  'Reconciliation job is reporting mismatches between the ledger and gateway for the last 3 hours. Growth is linear with traffic.',
  'com.acme.payment.ReconciliationException: ledger entry missing for txn 8f2a19
	at com.acme.payment.Reconciler.reconcileBatch(Reconciler.java:88)',
  'ReconciliationException',
  'src/main/java/com/acme/payment/Reconciler.java',
  88,
  'The retry path in LedgerClient silently drops entries when the batch commit times out. Deploy 2f41 introduced a shorter commit timeout without adjusting the retry policy.',
  'Increase the commit timeout back to 30s, or make LedgerClient enqueue failed entries for retry instead of dropping them.',
  'kubectl rollout undo deploy/payment-api -n production',
  0.88,
  NOW() - INTERVAL '3 hours',
  '{"demo_seed": true, "github": {"blame": {"commit_hash": "2f41a8b1", "author": "@marcus", "author_avatar": null, "message": "tune: reduce ledger commit timeout to 5s", "line": 88, "file": "src/main/java/com/acme/payment/Reconciler.java", "pr_number": 131, "pr_title": "tune: reduce ledger commit timeout to 5s", "pr_url": "https://github.com/acme-demo/payment-service/pull/131", "pr_author": "@marcus", "contributors": [{"username": "@marcus", "role": "author", "avatar": null, "url": null}]}, "related_prs": [{"number": 131, "title": "tune: reduce ledger commit timeout to 5s", "author": "@marcus", "url": "https://github.com/acme-demo/payment-service/pull/131", "merged_at": "2026-09-16T10:15:00Z", "files": ["src/main/java/com/acme/payment/Reconciler.java"], "relevance_score": 0.88, "reason": "PR #131 reduced the ledger commit timeout without updating the retry policy."}]}}'::jsonb,
  '["payment-api", "auth", "ledger", "fraud"]'::jsonb
),

-- ── 3. payment-api — P1 — ACTIVE ──────────────────────────────
(
  'INC-20260915-CC04A2',
  'payment-api',
  'P1',
  'active',
  'Elevated Card Decline Rate — Gateway Timeout Cascade',
  'Card decline rate 4x baseline since 09:00. Correlates with gateway response times above 2s.',
  'com.acme.payment.GatewayTimeoutException: card gateway did not respond within 2000ms
	at com.acme.payment.CardGateway.authorize(CardGateway.java:214)',
  'GatewayTimeoutException',
  'src/main/java/com/acme/payment/CardGateway.java',
  214,
  'Card gateway p99 latency has drifted from 400ms to 2.1s over the past 12 hours. Likely upstream capacity issue, but the client-side timeout is too tight to absorb it.',
  'Raise client timeout to 5s temporarily, and open a support ticket with the gateway provider.',
  'kubectl rollout undo deploy/payment-api -n production',
  0.72,
  NOW() - INTERVAL '1 day',
  '{"demo_seed": true}'::jsonb,
  '["payment-api", "auth", "ledger", "fraud"]'::jsonb
),

-- ── 4. auth — P0 — ACTIVE ─────────────────────────────────────
(
  'INC-20260916-D1E88F',
  'auth',
  'P0',
  'active',
  'Token Refresh Failing for OAuth Sessions',
  'OAuth refresh endpoint returning 500 for ~30% of requests. Users are being logged out mid-session.',
  'java.lang.IllegalStateException: session store returned null for refresh token rt_8a21f
	at com.acme.auth.TokenService.refresh(TokenService.java:156)',
  'IllegalStateException',
  'src/main/java/com/acme/auth/TokenService.java',
  156,
  'Session store eviction policy changed in the last deploy, evicting refresh tokens before their TTL. The null check downstream was never written because the eviction was assumed safe.',
  'Either restore the previous eviction policy, or add a null guard in TokenService.refresh and return a proper 401 instead of 500.',
  'kubectl rollout undo deploy/auth-service -n production',
  0.91,
  NOW() - INTERVAL '5 hours',
  '{"demo_seed": true, "github": {"blame": {"commit_hash": "b1a7c04e", "author": "@dana", "author_avatar": null, "message": "perf: tighten session store eviction window", "line": 156, "file": "src/main/java/com/acme/auth/TokenService.java", "pr_number": 204, "pr_title": "perf: tighten session store eviction window", "pr_url": "https://github.com/acme-demo/auth-service/pull/204", "pr_author": "@dana", "contributors": [{"username": "@dana", "role": "author", "avatar": null, "url": null}, {"username": "@wei", "role": "reviewer", "avatar": null, "url": null}]}, "related_prs": [{"number": 204, "title": "perf: tighten session store eviction window", "author": "@dana", "url": "https://github.com/acme-demo/auth-service/pull/204", "merged_at": "2026-09-15T14:00:00Z", "files": ["src/main/java/com/acme/auth/TokenService.java"], "relevance_score": 0.91, "reason": "PR #204 tightened the eviction window from 30min to 5min, well under the refresh token TTL."}]}}'::jsonb,
  '["auth", "user", "payment-api"]'::jsonb
),

-- ── 5. database — P0 — ACTIVE ─────────────────────────────────
(
  'INC-20260916-E5B33C',
  'database',
  'P0',
  'active',
  'Connection Pool Exhaustion Under Load',
  'All services reporting connection timeouts. Pool is at max connections with idle transactions from the reconciliation job.',
  'sqlalchemy.exc.TimeoutError: QueuePool limit of size 10 overflow 20 reached, connection timed out
	at src/db/pool.py:88',
  'TimeoutError',
  'src/db/pool.py',
  88,
  'Long-running reconciliation queries are holding transactions open past their expected duration. The pool size has not been adjusted since traffic grew 3x.',
  'Kill idle transactions older than 60s, increase pool size to 30 with a hard cap, and move reconciliation to a read replica.',
  'kubectl rollout restart statefulset/postgres -n production',
  0.87,
  NOW() - INTERVAL '7 hours',
  '{"demo_seed": true}'::jsonb,
  '["database", "ledger", "auth", "payment-api"]'::jsonb
),

-- ── 6. fraud — P1 — ACTIVE ────────────────────────────────────
(
  'INC-20260915-F9A21D',
  'fraud',
  'P1',
  'active',
  'Fraud Score Timeout During Peak Traffic',
  'Fraud scoring calls hitting the 500ms budget under peak load. Transactions are being declined by default on timeout.',
  'panic: context deadline exceeded
	at fraud_engine/score.go:142',
  'context.DeadlineExceeded',
  'internal/fraud_engine/score.go',
  142,
  'Model inference p99 has grown from 180ms to 780ms as the feature set expanded. The 500ms budget was set before the last model revision.',
  'Raise the scoring budget to 1500ms in the short term. Retrain with the feature set pruned to the top 20.',
  'kubectl rollout undo deploy/fraud-service -n production',
  0.79,
  NOW() - INTERVAL '1 day',
  '{"demo_seed": true}'::jsonb,
  '["fraud", "payment-api", "auth"]'::jsonb
),

-- ── 7. refund — P2 — RESOLVED ─────────────────────────────────
(
  'INC-20260914-A1B2C3',
  'refund',
  'P2',
  'resolved',
  'Refund Reversal Latency Spike',
  'Refund reversals taking 8–12s instead of the usual 1–2s. No customer impact yet, but SLO burn rate is elevated.',
  'java.util.concurrent.TimeoutException: reversal did not complete within 10000ms
	at com.acme.refund.ReversalService.process(ReversalService.java:201)',
  'TimeoutException',
  'src/main/java/com/acme/refund/ReversalService.java',
  201,
  'Reversal path was making three sequential calls to the ledger instead of one batch call. Latency compounded with each hop.',
  'Batch the ledger calls into a single transaction. Measured 8x improvement in staging.',
  'kubectl rollout undo deploy/refund-service -n production',
  0.81,
  NOW() - INTERVAL '2 days',
  '{"demo_seed": true, "auto_fix": {"status": "approved", "approved": true, "requires_approval": false, "mode": "pr_draft", "fix": "Batch the three ledger lookups into a single transaction.", "explanation": "The three sequential ledger calls at ReversalService.java:195-203 can be replaced with a single batched call.", "pr": {"status": "approved", "approval_required": false, "message": "✅ Fix approved (PR creation disabled by AUTO_FIX_MODE=read_only)"}}}'::jsonb,
  '["refund", "payment-api", "auth"]'::jsonb
),

-- ── 8. notification — P2 — RESOLVED ───────────────────────────
(
  'INC-20260913-B4D5E6',
  'notification',
  'P2',
  'resolved',
  'Email Delivery Delayed — Queue Backlog',
  'Email queue depth spiked to 40k messages. Delivery lag reached 22 minutes at peak.',
  'celery.exceptions.TimeoutError: task send_email exceeded soft time limit
	at notifications/tasks.py:74',
  'TimeoutError',
  'notifications/tasks.py',
  74,
  'A vendor migration on the SMTP provider reduced throughput by 60%. The queue absorbed it for 40 minutes before alerting fired.',
  'Switch to the new SMTP endpoint that was provisioned last month. Add a queue-depth alert at 10k messages.',
  'kubectl rollout restart deploy/notification-service -n production',
  0.76,
  NOW() - INTERVAL '3 days',
  '{"demo_seed": true}'::jsonb,
  '["notification", "user"]'::jsonb
),

-- ── 9. user — P2 — RESOLVED ───────────────────────────────────
(
  'INC-20260912-C7F8A9',
  'user',
  'P2',
  'resolved',
  'KYC Verification Stalled for New Signups',
  'New user KYC verifications queued but not processing. ~200 signups affected over 45 minutes.',
  'com.acme.user.KycException: vendor returned 401 for api key
	at com.acme.user.KycClient.verify(KycClient.java:92)',
  'KycException',
  'src/main/java/com/acme/user/KycClient.java',
  92,
  'The KYC vendor rotated their API key without notice. The old key was still in the vault and started returning 401.',
  'Rotate the key in vault and add a key-expiry alert 7 days before rotation is due.',
  'kubectl rollout restart deploy/user-service -n production',
  0.83,
  NOW() - INTERVAL '4 days',
  '{"demo_seed": true}'::jsonb,
  '["user"]'::jsonb
),

-- ── 10. ledger — P1 — RESOLVED ────────────────────────────────
(
  'INC-20260911-D1E2F3',
  'ledger',
  'P1',
  'resolved',
  'Ledger Entry Write Failures — Idempotency Key Collision',
  'Ledger writes failing with duplicate idempotency keys for entries that should be unique.',
  'sqlalchemy.exc.IntegrityError: duplicate key value violates unique constraint "ledger_idempotency_key_key"
	at ledger/writer.py:118',
  'IntegrityError',
  'ledger/writer.py',
  118,
  'The idempotency key was derived from a timestamp with second-level precision. Under burst traffic, two entries in the same second collided.',
  'Switch the key derivation to a UUIDv7, which is monotonic and collision-free. Backfill existing rows.',
  'kubectl rollout restart deploy/ledger-service -n production',
  0.89,
  NOW() - INTERVAL '5 days',
  '{"demo_seed": true, "auto_fix": {"status": "pr_draft", "approved": false, "requires_approval": true, "mode": "pr_draft", "approval_url": "/approve/INC-20260911-D1E2F3", "fix_preview": "@@ -116,3 +116,3 @@ - key = f(entry.ts):(entry.account) + key = str(uuid.uuid7())", "explanation": "Replace the timestamp-derived idempotency key with UUIDv7, which is monotonic and collision-free under burst traffic.", "pr": {"status": "pr_draft", "approval_required": true, "approval_url": "/approve/INC-20260911-D1E2F3"}}}'::jsonb,
  '["ledger", "database", "payment-api"]'::jsonb
),

-- ── 11. auth — P1 — RESOLVED ──────────────────────────────────
(
  'INC-20260910-E4F5A6',
  'auth',
  'P1',
  'resolved',
  'Elevated Login Latency — Session Store Contention',
  'Login p99 latency 3.2s, up from 400ms baseline. All paths through the session store.',
  'java.util.concurrent.TimeoutException: could not acquire session store lock within 500ms
	at com.acme.auth.SessionStore.acquire(SessionStore.java:134)',
  'TimeoutException',
  'src/main/java/com/acme/auth/SessionStore.java',
  134,
  'Session store lock granularity was per-tenant, not per-session. Under peak login traffic, tenants with many concurrent logins serialized.',
  'Switch to per-session locking using a striped lock across 256 buckets. Measured 12x throughput in staging.',
  'kubectl rollout undo deploy/auth-service -n production',
  0.86,
  NOW() - INTERVAL '6 days',
  '{"demo_seed": true}'::jsonb,
  '["auth", "user"]'::jsonb
);
