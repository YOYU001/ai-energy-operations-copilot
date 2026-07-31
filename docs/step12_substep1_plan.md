# Step 12 Sub-step 1 — Conversation Schema Plan

> Planning document only. No schema/query-layer code has been written yet;
> this file is the reviewed source of truth before implementation begins.
> Incorporates the Step 11-precedent guarded-migration pattern and the
> concurrency/connection-lifecycle fixes surfaced by a Codex cross-review
> of an earlier draft of this plan.

## 1. Guarded Migration SQL

The existing `chat_messages` table (`database/schema.sql`) is a Step 1-era
placeholder (`id, session_id, role, content, created_at`) with zero rows in
the dev DB today. Rather than a one-time `DROP TABLE` (which would silently
destroy real conversation data the next time anyone re-runs `schema.sql`
after Step 12 ships), this uses the same guarded-upgrade pattern already
established for `case_records` in Step 11: `ADD COLUMN IF NOT EXISTS` for
every new column, then existence-checked `ALTER`/`ADD CONSTRAINT`
statements guarded by `information_schema.columns` / `pg_constraint`
lookups, so re-running this block on an already-upgraded table is always a
no-op.

```sql
CREATE TABLE IF NOT EXISTS conversations (
    id SERIAL PRIMARY KEY,
    title TEXT,
    role_mode TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    archived_at TIMESTAMP
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'conversations_role_mode_check'
          AND conrelid = 'conversations'::regclass
    ) THEN
        ALTER TABLE conversations ADD CONSTRAINT conversations_role_mode_check
            CHECK (role_mode IS NULL OR role_mode IN ('operator', 'engineer', 'executive', 'training'));
    END IF;
END $$;

DO $$
BEGIN
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS conversation_id INTEGER;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS status TEXT;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS citations JSONB;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS tool_calls JSONB;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS parent_user_message_id INTEGER;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS attempt_number INTEGER;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS is_active BOOLEAN;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS regenerated_from_message_id INTEGER;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS provider TEXT;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS model TEXT;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS model_version TEXT;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS finish_reason TEXT;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS usage JSONB;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS error_message TEXT;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS started_at TIMESTAMP;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP;
    ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'chat_messages' AND column_name = 'updated_at' AND column_default IS NOT NULL
    ) THEN
        ALTER TABLE chat_messages ALTER COLUMN updated_at SET DEFAULT now();
    END IF;
    UPDATE chat_messages SET updated_at = COALESCE(updated_at, created_at, now()) WHERE updated_at IS NULL;
    ALTER TABLE chat_messages ALTER COLUMN updated_at SET NOT NULL;

    -- Never assume "currently empty" is a permanent fact. Any row still
    -- missing conversation_id (the old placeholder schema never had this
    -- column, so any pre-Step-12 row will be NULL here) is treated as
    -- orphaned data this migration cannot safely re-home on its own.
    -- It aborts loudly instead of guessing or discarding.
    IF EXISTS (SELECT 1 FROM chat_messages WHERE conversation_id IS NULL) THEN
        RAISE EXCEPTION 'chat_messages upgrade aborted: % row(s) exist with no conversation_id -- back up/export or manually resolve them before re-running schema.sql. This upgrade never silently discards or auto-assigns orphaned rows to a conversation.',
            (SELECT count(*) FROM chat_messages WHERE conversation_id IS NULL);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'chat_messages' AND column_name = 'conversation_id' AND is_nullable = 'NO'
    ) THEN
        ALTER TABLE chat_messages ALTER COLUMN conversation_id SET NOT NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chat_messages_conversation_id_fkey'
          AND conrelid = 'chat_messages'::regclass
    ) THEN
        ALTER TABLE chat_messages
            ADD CONSTRAINT chat_messages_conversation_id_fkey
            FOREIGN KEY (conversation_id) REFERENCES conversations(id);
    END IF;

    UPDATE chat_messages SET attempt_number = 1 WHERE attempt_number IS NULL;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'chat_messages' AND column_name = 'attempt_number' AND is_nullable = 'NO'
    ) THEN
        ALTER TABLE chat_messages ALTER COLUMN attempt_number SET NOT NULL;
    END IF;
    ALTER TABLE chat_messages ALTER COLUMN attempt_number SET DEFAULT 1;

    UPDATE chat_messages SET is_active = true WHERE is_active IS NULL;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'chat_messages' AND column_name = 'is_active' AND is_nullable = 'NO'
    ) THEN
        ALTER TABLE chat_messages ALTER COLUMN is_active SET NOT NULL;
    END IF;
    ALTER TABLE chat_messages ALTER COLUMN is_active SET DEFAULT true;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'chat_messages' AND column_name = 'status' AND is_nullable = 'NO'
    ) THEN
        UPDATE chat_messages SET status = 'completed' WHERE status IS NULL;
        ALTER TABLE chat_messages ALTER COLUMN status SET NOT NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chat_messages_role_check'
          AND conrelid = 'chat_messages'::regclass
    ) THEN
        ALTER TABLE chat_messages ADD CONSTRAINT chat_messages_role_check
            CHECK (role IN ('user', 'assistant'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chat_messages_status_check'
          AND conrelid = 'chat_messages'::regclass
    ) THEN
        ALTER TABLE chat_messages ADD CONSTRAINT chat_messages_status_check
            CHECK (status IN ('streaming', 'completed', 'aborted', 'failed'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chat_messages_attempt_number_check'
          AND conrelid = 'chat_messages'::regclass
    ) THEN
        ALTER TABLE chat_messages ADD CONSTRAINT chat_messages_attempt_number_check
            CHECK (attempt_number >= 1);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chat_messages_role_shape_check'
          AND conrelid = 'chat_messages'::regclass
    ) THEN
        ALTER TABLE chat_messages ADD CONSTRAINT chat_messages_role_shape_check
            CHECK (
                (role = 'user'
                    AND parent_user_message_id IS NULL
                    AND regenerated_from_message_id IS NULL
                    AND status = 'completed')
                OR
                (role = 'assistant'
                    AND parent_user_message_id IS NOT NULL)
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chat_messages_parent_fkey'
          AND conrelid = 'chat_messages'::regclass
    ) THEN
        ALTER TABLE chat_messages
            ADD CONSTRAINT chat_messages_parent_fkey
            FOREIGN KEY (parent_user_message_id) REFERENCES chat_messages(id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chat_messages_regenerated_from_fkey'
          AND conrelid = 'chat_messages'::regclass
    ) THEN
        ALTER TABLE chat_messages
            ADD CONSTRAINT chat_messages_regenerated_from_fkey
            FOREIGN KEY (regenerated_from_message_id) REFERENCES chat_messages(id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chat_messages_parent_attempt_key'
          AND conrelid = 'chat_messages'::regclass
    ) THEN
        ALTER TABLE chat_messages
            ADD CONSTRAINT chat_messages_parent_attempt_key
            UNIQUE (parent_user_message_id, attempt_number);
    END IF;

    -- session_id has no equivalent in the new model (conversation_id
    -- replaces its role) -- but proving every row now has a conversation_id
    -- does NOT by itself prove session_id's own values are redundant or
    -- safely discardable (Codex review, fix #1). Require an explicit,
    -- separate check: only drop the column when every surviving row's
    -- session_id is already NULL.
    --
    -- This whole step must be guarded by a column-existence check (Codex
    -- second-pass review): once a prior run has already dropped
    -- session_id, a bare `SELECT ... WHERE session_id IS NOT NULL` on a
    -- later run would fail with "column does not exist" the moment this
    -- statement is reached, breaking re-runnability. Wrapping it in this
    -- outer IF means the value-check query is only ever planned/executed
    -- while the column still exists; once it's gone, this entire branch is
    -- skipped and the migration stays a no-op here on every subsequent run.
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'chat_messages' AND column_name = 'session_id'
    ) THEN
        IF EXISTS (SELECT 1 FROM chat_messages WHERE session_id IS NOT NULL) THEN
            RAISE EXCEPTION 'chat_messages upgrade aborted: % row(s) still have a non-null session_id -- session_id is being retired in favor of conversation_id; export/verify this data is safe to discard, then either NULL it out manually or re-run schema.sql with the session_id DROP COLUMN step skipped for this pass.',
                (SELECT count(*) FROM chat_messages WHERE session_id IS NOT NULL);
        END IF;
        ALTER TABLE chat_messages DROP COLUMN session_id;
    END IF;

    -- created_at was nullable with no default in the old placeholder
    -- schema (Codex review, fix #2) -- backfill any legacy NULLs, then
    -- guardedly add a default and NOT NULL so both existing rows and the
    -- (conversation_id, created_at, id) index below always have a real,
    -- ordering-safe timestamp.
    UPDATE chat_messages SET created_at = COALESCE(created_at, now()) WHERE created_at IS NULL;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'chat_messages' AND column_name = 'created_at' AND column_default IS NOT NULL
    ) THEN
        ALTER TABLE chat_messages ALTER COLUMN created_at SET DEFAULT now();
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'chat_messages' AND column_name = 'created_at' AND is_nullable = 'NO'
    ) THEN
        ALTER TABLE chat_messages ALTER COLUMN created_at SET NOT NULL;
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS chat_messages_active_attempt_key
    ON chat_messages (parent_user_message_id) WHERE is_active;

CREATE INDEX IF NOT EXISTS chat_messages_conversation_created_idx
    ON chat_messages (conversation_id, created_at, id);

CREATE INDEX IF NOT EXISTS conversations_active_updated_idx
    ON conversations (updated_at) WHERE archived_at IS NULL;
```

### Constraint-existence checks are table-scoped

Every `pg_constraint` lookup above filters on both `conname` AND
`conrelid = '<table>'::regclass`, so a same-named constraint that happens
to exist on an unrelated table can never cause this migration to
incorrectly skip creating the constraint it actually needs on
`chat_messages`/`conversations`.

### Handling a non-empty legacy `chat_messages`

This migration never assumes "currently zero rows" as a permanent fact.
The real protection is generic: on every execution, if any row still has
`conversation_id IS NULL`, the block `RAISE EXCEPTION`s and aborts before
touching constraints. Because the old placeholder schema never had a
`conversation_id` column at all, any row that existed before this upgrade
ran will always show up as `conversation_id IS NULL` afterward — so this
same check correctly catches both "the table happens to be empty today"
and "somehow there is legacy data" without ever guessing which conversation
an orphaned row should belong to, and without ever silently deleting it.

### `session_id` removal

Decision: drop it, but only after an explicit, dedicated guard (separate
from the `conversation_id` orphan check) confirms every surviving row's
`session_id` is already `NULL`. Proving a row now has a `conversation_id`
does not by itself prove its `session_id` value was safe to lose — those
are two independent facts, and this plan checks both before the column is
actually dropped.

## 2. Regenerate Transaction (concurrency-safe)

Per the connection-ownership contract in section 3, `create_regenerate_attempt`
does **not** issue its own `BEGIN`/`COMMIT`/`ROLLBACK` — it receives an
external `conn` and runs the six steps below against it; the **caller**
commits once after the function returns successfully, or rolls back if it
raises. The statements are shown here without literal `BEGIN;`/`COMMIT;`
to avoid implying the function manages its own transaction (Codex review,
fix #3 residual).

```sql
-- Step 1: lock the parent user message so concurrent regenerate requests
-- for the same message serialize instead of racing.
SELECT id, conversation_id, role
FROM chat_messages
WHERE id = :parent_user_message_id
FOR UPDATE;
-- No row found -> function raises ParentMessageNotFound; the caller rolls back.

-- Step 2: validate (checked in application code against the row above;
-- any failure -> function raises, does not proceed to step 3; the caller
-- rolls back and never calls commit).
--   a. row.role must equal 'user'                     -> else InvalidRegenerateTarget
--   b. row.conversation_id must equal :conversation_id -> else ConversationMismatch

-- Step 3: find the current max attempt_number for this parent.
SELECT COALESCE(MAX(attempt_number), 0) AS max_attempt
FROM chat_messages
WHERE parent_user_message_id = :parent_user_message_id;

-- Step 4: find the currently active assistant attempt id, if any
-- (used for regenerated_from_message_id; NULL is valid if none is active,
-- e.g. regenerating after every prior attempt failed before ever
-- being marked active).
SELECT id
FROM chat_messages
WHERE parent_user_message_id = :parent_user_message_id AND is_active = true;

-- Step 5: retire the old active attempt.
UPDATE chat_messages
SET is_active = false, updated_at = now()
WHERE parent_user_message_id = :parent_user_message_id AND is_active = true;

-- Step 6: insert the new attempt. created_at is passed explicitly (now())
-- rather than relying solely on the column default, per Codex review fix #2.
INSERT INTO chat_messages (
    conversation_id, role, content, status,
    parent_user_message_id, attempt_number, is_active,
    regenerated_from_message_id, provider, model, started_at, created_at
) VALUES (
    :conversation_id, 'assistant', '', 'streaming',
    :parent_user_message_id, :max_attempt + 1, true,
    :old_active_message_id, :provider, :model, now(), now()
)
RETURNING id;
```

> Note: the `:name` tokens above are SQLAlchemy `text()` bind parameters
> (matching this repo's existing query-layer convention, e.g.
> `backend/app/case_records_queries.py`), not directly executable raw
> `psql` syntax.

**Commit/rollback behavior**: any validation failure in step 2 causes the
function to raise immediately, without executing steps 3-6; the **caller**
catches that exception, does not commit, and rolls back — the API layer
then maps the specific exception type to a 404 (parent not found) or 409
(wrong role/conversation). If all six steps succeed, the function returns
the new assistant message id and the **caller** issues a single commit,
then proceeds to the streaming generation flow.

**Unique-violation handling**: because step 1's `FOR UPDATE` already
serializes concurrent regenerate calls against the same
`parent_user_message_id`, the insert in step 6 should never actually
collide with `chat_messages_parent_attempt_key` in normal operation. If it
somehow does (e.g. a locking bug), `create_regenerate_attempt` lets that
specific unique-violation exception propagate; the **caller** catches it,
rolls back, and returns a 409 asking the client to retry — this constraint
is a last-resort safety net, not an expected code path, and handling it is
still the caller's responsibility, consistent with the connection-ownership
contract (the function itself never rolls back on its own).

**Stated isolation/locking assumption (Codex review, fix #5)**: this design
is safe under Postgres's default `READ COMMITTED` isolation level. The
locking contract has exactly two paths, with deliberately different
treatment:

- **Every regenerate call** (i.e. every path creating a *subsequent*
  attempt for a `parent_user_message_id` that may already have one or more
  existing attempts) **must** take the `SELECT ... FOR UPDATE` lock on the
  parent row before computing `attempt_number`/`is_active` changes.
  `create_regenerate_attempt` is currently the only such path, and it does
  this.
- **The first attempt** for a brand-new user message
  (`create_streaming_assistant_placeholder`) is the one explicit,
  named exception to that rule — it does *not* take the lock, because
  under normal application flow there is no pre-existing attempt row to
  race against for a message that was just inserted. This is a deliberate
  carve-out, not an oversight or a gap in "every path must lock": the
  known residual risk it accepts is a double-submit of the same user
  message (e.g. a double-click before the UI disables the send button)
  racing two concurrent first-attempt inserts, and
  `chat_messages_parent_attempt_key` is the accepted backstop for exactly
  that case (one insert wins, the other fails and the API layer maps it to
  a 409) — the same "constraint as last line of defense" pattern already
  used for regenerate's own unique-violation handling above. Sub-step 1
  does not add `FOR UPDATE` locking to the first-attempt path; the
  unique-constraint backstop is treated as sufficient for it.

## 3. Query Layer

**Connection-ownership contract (Codex review, fix #3)**: every function
below follows the *same* convention already established by
`backend/app/case_records_queries.py` and the rest of this codebase's
query layer — each function accepts an external `conn` parameter passed in
by the caller and performs **no commit/rollback of its own**; the caller
owns the transaction boundary. This replaces an earlier, self-contradictory
draft of this document that alternated between "the function commits
internally" and "the caller may reuse the connection." There is no
deliberate deviation from the Step 11 convention here — Sub-step 1 follows
it exactly.

| Function | Input | Output | SQL | Caller's transaction boundary |
|---|---|---|---|---|
| `create_conversation` | `conn, role_mode` | new `id` | single INSERT | caller commits immediately after this call |
| `list_conversations` | `conn, limit, offset` | `(total, items)`, excludes archived | two SELECTs | read-only, no commit needed |
| `get_conversation_with_active_messages` | `conn, conversation_id` | conversation + messages where `is_active=true`, ordered by `created_at` | two SELECTs | read-only, no commit needed |
| `update_conversation` | `conn, conversation_id, title, role_mode` | updated row | single UPDATE (also bumps `updated_at`) | caller commits immediately after |
| `archive_conversation` | `conn, conversation_id` | rows affected | single UPDATE setting `archived_at=now()` | caller commits immediately after |
| `insert_user_message` | `conn, conversation_id, content` | new `id` | INSERT (`role='user', status='completed'`) + conditional `UPDATE conversations SET title=... WHERE id=:id AND title IS NULL` | both statements execute against the same `conn` before the caller's single commit — the caller must not commit between them |
| `create_streaming_assistant_placeholder` | `conn, conversation_id, parent_user_message_id, attempt_number, provider, model` | new `id` | single INSERT (`role='assistant', status='streaming', is_active=true, started_at=now()`) | caller commits immediately after |
| `finalize_assistant_message` | `conn, message_id, content, status, error_message, finish_reason, usage` | rows affected (0 or 1) | single UPDATE, `WHERE status='streaming'` (idempotent) | caller commits immediately after; see connection-lifecycle note below on *which* connection this must be |
| `create_regenerate_attempt` | `conn, conversation_id, parent_user_message_id, provider, model` | new `id` | all six steps from section 2 | all six steps execute against the same `conn`; the caller issues exactly one commit after the function returns (or rolls back if it raises) |
| `mark_stale_streaming_messages_as_failed` | `conn` | rows affected | single UPDATE | caller commits immediately after; *when/how often this is invoked is startup/lifecycle wiring, out of scope for this document — see below* |

### Connection-lifecycle contract

1. **`insert_user_message` and `create_streaming_assistant_placeholder` are
   two separate caller-committed transactions**, not one. The caller may
   pass the same `conn` to both calls back-to-back (with a commit after
   each), but they are two separate facts (what the user said vs. that
   generation has begun) with no need for all-or-nothing atomicity between
   them.
2. **No query function itself waits on an LLM or tool call.** Every
   function above is "run SQL against the `conn` it was given, return" —
   none of them block on network/provider I/O internally. This is what
   lets the future Streaming API sub-step hold zero DB connections during
   Phase A/B: it simply does not call any of these functions during that
   window.
3. **`create_regenerate_attempt` is the one function whose caller must
   treat it as a single atomic unit** — commit only after it returns
   successfully, rollback if it raises — because splitting the six steps
   across separate commits would defeat the purpose of the `FOR UPDATE`
   lock.
4. **`finalize_assistant_message` must be called with a connection acquired
   specifically for that call, not the same connection the initiating
   request held for `insert_user_message`/`create_streaming_assistant_placeholder`
   (Codex review, fix #4).** This is a concrete, checkable requirement for
   the future Streaming API sub-step, not just a documented convention:
   `backend/app/db.py`'s current FastAPI dependency holds one connection
   for the whole request lifetime, so the Streaming API sub-step must
   explicitly open a *new* connection (e.g. its own `with get_connection()`
   block) after Phase A/B ends, rather than reusing the request-scoped
   dependency-injected connection across the orchestration gap. Recorded
   here as a hard constraint for whoever implements that sub-step; nothing
   in Sub-step 1 itself needs to enforce it in code.

## 4. Sub-step 1 Acceptance Criteria

- Applying this migration to the dev DB and inspecting `conversations` /
  `chat_messages` (`\d` in psql) shows every column, type, `NOT NULL`,
  default, foreign key, `CHECK` constraint, and index exactly matching
  section 1.
- Re-applying the full `schema.sql` a second time is a no-op on an
  already-upgraded database (no errors, nothing re-created, no re-running
  of backfill `UPDATE`s beyond harmless idempotent no-ops).
- Simulating a legacy `chat_messages` row with `conversation_id IS NULL`
  (impossible to have any other way, since the old schema never had that
  column) causes the migration to `RAISE EXCEPTION` and abort, never
  silently deleting or auto-assigning it.
- All five `CHECK` constraints
  (`conversations_role_mode_check`, `chat_messages_role_check`,
  `chat_messages_status_check`, `chat_messages_attempt_number_check`,
  `chat_messages_role_shape_check`) can actually be triggered by inserting
  invalid data, and every existence check that guards creating them is
  scoped by `conrelid`.
- `chat_messages_parent_attempt_key` and `chat_messages_active_attempt_key`
  both correctly reject violating data.
- **Concurrency for `create_regenerate_attempt` must be proven against a
  real PostgreSQL database, not fake connections (Codex review, fix #6).**
  `backend/tests/fakes.py`'s `FakeConnection`/`FakeCaseRecordsConnection`
  only record/dispatch SQL on a single simulated connection — they do not
  implement actual row locking, so they cannot validate that `FOR UPDATE`
  really serializes two concurrent callers. This needs a dedicated
  integration test that opens two real connections against the dev/test
  Postgres database, fires two concurrent `create_regenerate_attempt`
  calls for the same `parent_user_message_id`, and asserts: both complete
  without error, their `attempt_number`s do not collide, and exactly one
  resulting row has `is_active=true`. This mirrors the existing project
  convention of pairing fake-connection unit tests with a separate
  real-database integration test for anything the fakes structurally
  cannot verify (e.g. Step 10's real-DB idempotent-upsert verification).
- All ten query-layer functions in section 3 additionally have
  fake-connection unit tests (matching the existing
  `test_case_records_queries.py`/`fakes.py` convention) for SQL shape and
  error paths — these are necessary but, per the point above, not
  sufficient on their own to prove the concurrency guarantee. At minimum
  cover: conditional title update on `insert_user_message`, idempotent
  no-op on `finalize_assistant_message` when the message is no longer
  `streaming`, both invalid-input paths for `create_regenerate_attempt`
  (wrong role, wrong conversation), and correct behavior of
  `mark_stale_streaming_messages_as_failed` given a `conn` with pre-seeded
  `streaming` rows.
- Full-repo `pytest` passes. This sub-step does not touch the frontend, so
  `npm run lint` / `npm run build` are unaffected.

## Explicitly out of scope for Sub-step 1

Streaming API wiring, `ChatProvider`/model calls, tool-calling
orchestration, SSE event formatting, background sweep, multi-worker
coordination, chat UI, and citation-token validation are NOT part of this
document — they belong to later Step 12 sub-steps and are tracked
separately in the conversation history, not restated here.

Also explicitly out of scope (Codex review, fix #7): *when and how often*
`mark_stale_streaming_messages_as_failed` gets invoked — "once at backend
startup," "on a dedicated startup-only connection," or any other
scheduling/lifecycle decision — is orchestration/lifecycle wiring that
belongs to the Streaming API sub-step. Sub-step 1 delivers only the query
function itself (accepting an externally-supplied `conn`, per the
connection-ownership contract above) and its tests; it does not implement
or decide how the function gets called in practice.
