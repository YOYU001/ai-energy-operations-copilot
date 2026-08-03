"""Step 12 Sub-step 1: conversations / chat_messages query layer.

Function-based, dependency-injected style (conn passed in, no commit/
rollback inside these functions -- the caller owns transaction boundaries),
matching the existing convention in datasets_queries.py / case_records_queries.py.
See docs/step12_substep1_plan.md for the full design rationale (guarded
migration, regenerate locking contract, connection-ownership contract);
this module implements exactly that plan, reviewed end-to-end by three
rounds of independent read-only Codex review before implementation.

create_regenerate_attempt is the one function in this module that performs
multiple SQL statements as a single logical unit -- SELECT ... FOR UPDATE
to lock the parent user message, validate it, compute the next
attempt_number, retire the old active attempt, and insert the new one. The
caller must run it all against one conn and commit only after it returns
successfully (or roll back if it raises), matching the general
connection-ownership contract above: this function itself never commits
or rolls back.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from sqlalchemy import text


class ParentMessageNotFound(Exception):
    """Raised by create_regenerate_attempt when parent_user_message_id does
    not exist. The caller maps this to a 404."""


class InvalidRegenerateTarget(Exception):
    """Raised by create_regenerate_attempt when the referenced message is
    not a user message (role != 'user'). Per docs/step12_substep3c_plan.md
    section 4, the caller maps this to a 400 (corrected from an earlier
    docstring here that said 409, written before that endpoint's contract
    was decided)."""


class ConversationMismatch(Exception):
    """Raised by create_regenerate_attempt when the referenced message
    belongs to a different conversation than the one supplied. Per
    docs/step12_substep3c_plan.md section 4, the caller maps this to a 404
    (treated identically to "message does not exist", to avoid disclosing
    that the id belongs to a different conversation -- corrected from an
    earlier docstring here that said 409)."""


class RegenerateAlreadyInProgress(Exception):
    """Step 12 Sub-step 3C: raised by create_regenerate_attempt when the
    parent's current active attempt is still status='streaming'. The
    caller maps this to a 409. This check runs INSIDE the FOR UPDATE-locked
    transaction on the parent row, not as a separate route-level
    pre-check -- a route-level SELECT-then-create has a TOCTOU race (two
    concurrent requests could both pass a plain SELECT before either
    commits); only a check made inside the same lock scope that also
    performs the create is race-free. See docs/step12_substep3c_plan.md
    section 6."""


def create_conversation(conn, role_mode: Optional[str] = None) -> int:
    """Insert a new conversation with no title (title is set later, the
    first time a user message is inserted -- see insert_user_message)."""
    result = conn.execute(
        text("INSERT INTO conversations (role_mode) VALUES (:role_mode) RETURNING id"),
        {"role_mode": role_mode},
    )
    return result.scalar_one()


def list_conversations(conn, limit: int, offset: int) -> tuple[int, list[dict]]:
    """Return (total, items) for a page of non-archived conversations,
    most recently updated first."""
    total = conn.execute(
        text("SELECT COUNT(*) AS total FROM conversations WHERE archived_at IS NULL")
    ).mappings().first()["total"]
    rows = conn.execute(
        text(
            """
            SELECT * FROM conversations
            WHERE archived_at IS NULL
            ORDER BY updated_at DESC, id DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        {"limit": limit, "offset": offset},
    ).mappings().all()
    return total, [dict(row) for row in rows]


def get_conversation_with_active_messages(conn, conversation_id: int) -> Optional[dict]:
    """Return {"conversation": dict, "messages": list[dict]} for this
    conversation, or None if it doesn't exist. messages only includes rows
    where is_active=true, ordered chronologically."""
    conversation = conn.execute(
        text("SELECT * FROM conversations WHERE id = :id"),
        {"id": conversation_id},
    ).mappings().first()
    if conversation is None:
        return None

    messages = conn.execute(
        text(
            """
            SELECT * FROM chat_messages
            WHERE conversation_id = :conversation_id AND is_active = true
            ORDER BY created_at, id
            """
        ),
        {"conversation_id": conversation_id},
    ).mappings().all()
    return {"conversation": dict(conversation), "messages": [dict(m) for m in messages]}


def update_conversation(
    conn,
    conversation_id: int,
    title: Optional[str] = None,
    role_mode: Optional[str] = None,
) -> Optional[dict]:
    """Update title and/or role_mode. Only overwrites fields explicitly
    passed (None means "leave unchanged" for both title and role_mode, so
    this can be called to rename without also clearing role_mode and vice
    versa). Returns the updated row, or None if conversation_id doesn't
    exist."""
    row = conn.execute(
        text(
            """
            UPDATE conversations
            SET title = COALESCE(:title, title),
                role_mode = COALESCE(:role_mode, role_mode),
                updated_at = now()
            WHERE id = :id
            RETURNING *
            """
        ),
        {"id": conversation_id, "title": title, "role_mode": role_mode},
    ).mappings().first()
    return dict(row) if row else None


def archive_conversation(conn, conversation_id: int) -> int:
    """Soft-delete: set archived_at. Returns rows affected (0 or 1)."""
    result = conn.execute(
        text(
            """
            UPDATE conversations
            SET archived_at = now(), updated_at = now()
            WHERE id = :id AND archived_at IS NULL
            """
        ),
        {"id": conversation_id},
    )
    return result.rowcount


def insert_user_message(conn, conversation_id: int, content: str) -> int:
    """Insert a user message (always role='user', status='completed'), and
    -- in the same conn, before the caller's commit -- backend-generate the
    conversation's title from this content if the conversation doesn't
    already have one. Truncates to the first ~40 characters; never calls
    an LLM for this."""
    message_id = conn.execute(
        text(
            """
            INSERT INTO chat_messages (conversation_id, role, content, status)
            VALUES (:conversation_id, 'user', :content, 'completed')
            RETURNING id
            """
        ),
        {"conversation_id": conversation_id, "content": content},
    ).scalar_one()

    conn.execute(
        text(
            """
            UPDATE conversations
            SET title = left(:content, 40), updated_at = now()
            WHERE id = :conversation_id AND title IS NULL
            """
        ),
        {"conversation_id": conversation_id, "content": content},
    )
    return message_id


def create_streaming_assistant_placeholder(
    conn,
    conversation_id: int,
    parent_user_message_id: int,
    attempt_number: int,
    provider: Optional[str],
    model: Optional[str],
) -> int:
    """Insert the first assistant attempt for a user message
    (attempt_number is normally 1 here; regenerate uses
    create_regenerate_attempt instead, which computes its own
    attempt_number under a lock)."""
    result = conn.execute(
        text(
            """
            INSERT INTO chat_messages (
                conversation_id, role, content, status,
                parent_user_message_id, attempt_number, is_active,
                provider, model, started_at
            ) VALUES (
                :conversation_id, 'assistant', '', 'streaming',
                :parent_user_message_id, :attempt_number, true,
                :provider, :model, now()
            )
            RETURNING id
            """
        ),
        {
            "conversation_id": conversation_id,
            "parent_user_message_id": parent_user_message_id,
            "attempt_number": attempt_number,
            "provider": provider,
            "model": model,
        },
    )
    return result.scalar_one()


def finalize_assistant_message(
    conn,
    message_id: int,
    content: str,
    status: str,
    error_message: Optional[str],
    finish_reason: Optional[str],
    usage: Optional[dict],
) -> int:
    """Idempotent terminal-state update: only transitions a message that is
    still 'streaming'. Returns rows affected (0 or 1) so the caller can
    detect a no-op (already finalized) versus a real transition. Expected
    to be called with a connection acquired specifically for this call, not
    the connection the initiating request held for insert_user_message /
    create_streaming_assistant_placeholder (see docs/step12_substep1_plan.md
    section 3, connection-lifecycle contract point 4)."""
    result = conn.execute(
        text(
            """
            UPDATE chat_messages
            SET content = :content,
                status = :status,
                error_message = :error_message,
                finish_reason = :finish_reason,
                usage = CAST(:usage AS JSONB),
                completed_at = COALESCE(completed_at, now()),
                updated_at = now()
            WHERE id = :message_id AND status = 'streaming'
            """
        ),
        {
            "message_id": message_id,
            "content": content,
            "status": status,
            "error_message": error_message,
            "finish_reason": finish_reason,
            "usage": json.dumps(usage) if usage is not None else None,
        },
    )
    return result.rowcount


def create_regenerate_attempt(
    conn,
    conversation_id: int,
    parent_user_message_id: int,
    provider: Optional[str],
    model: Optional[str],
) -> int:
    """Concurrency-safe regenerate: locks the parent user message with
    SELECT ... FOR UPDATE so concurrent regenerate calls for the same
    parent serialize instead of racing, validates it, rejects (raises
    RegenerateAlreadyInProgress) if the current active attempt is still
    status='streaming' (Step 12 Sub-step 3C), otherwise retires the
    current active attempt and inserts a new one with attempt_number+1.
    All statements below run against the same conn; this function issues
    no commit/rollback of its own -- the caller commits once after this
    returns, or rolls back if it raises.
    """
    parent = conn.execute(
        text("SELECT id, conversation_id, role FROM chat_messages WHERE id = :id FOR UPDATE"),
        {"id": parent_user_message_id},
    ).mappings().first()
    if parent is None:
        raise ParentMessageNotFound(parent_user_message_id)
    if parent["role"] != "user":
        raise InvalidRegenerateTarget(parent_user_message_id)
    if parent["conversation_id"] != conversation_id:
        raise ConversationMismatch(parent_user_message_id)

    # Step 12 Sub-step 3C: widened to also fetch status (was `SELECT id`
    # only) so the in-flight guard below can check it without a second
    # query -- old_active_message_id (used later for
    # regenerated_from_message_id) is still derived from this same row.
    old_active = conn.execute(
        text(
            "SELECT id, status FROM chat_messages "
            "WHERE parent_user_message_id = :parent_user_message_id AND is_active = true"
        ),
        {"parent_user_message_id": parent_user_message_id},
    ).mappings().first()
    if old_active is not None and old_active["status"] == "streaming":
        raise RegenerateAlreadyInProgress(parent_user_message_id)
    old_active_message_id = old_active["id"] if old_active else None

    max_attempt = conn.execute(
        text(
            "SELECT COALESCE(MAX(attempt_number), 0) AS max_attempt FROM chat_messages "
            "WHERE parent_user_message_id = :parent_user_message_id"
        ),
        {"parent_user_message_id": parent_user_message_id},
    ).mappings().first()["max_attempt"]

    conn.execute(
        text(
            """
            UPDATE chat_messages
            SET is_active = false, updated_at = now()
            WHERE parent_user_message_id = :parent_user_message_id AND is_active = true
            """
        ),
        {"parent_user_message_id": parent_user_message_id},
    )

    new_id = conn.execute(
        text(
            """
            INSERT INTO chat_messages (
                conversation_id, role, content, status,
                parent_user_message_id, attempt_number, is_active,
                regenerated_from_message_id, provider, model, started_at, created_at
            ) VALUES (
                :conversation_id, 'assistant', '', 'streaming',
                :parent_user_message_id, :attempt_number, true,
                :old_active_message_id, :provider, :model, now(), now()
            )
            RETURNING id
            """
        ),
        {
            "conversation_id": conversation_id,
            "parent_user_message_id": parent_user_message_id,
            "attempt_number": max_attempt + 1,
            "old_active_message_id": old_active_message_id,
            "provider": provider,
            "model": model,
        },
    ).scalar_one()
    return new_id


def record_tool_activity(
    conn,
    message_id: int,
    tool_calls: Optional[list[dict]],
    citations: Optional[list[dict]],
) -> int:
    """Step 12 Sub-step 3B: persists this message's tool-call audit trail
    and structured citations into the tool_calls/citations JSONB columns
    (added by the Sub-step 1 migration, unused until this function).
    Deliberately a separate function rather than a new parameter on
    finalize_assistant_message -- keeps that function single-purpose
    (status-transition only), matching the earlier decision not to widen
    its signature. Callers run this in the same connection/transaction as
    finalize_assistant_message, after it, and commit once for both.
    Returns rows affected (0 or 1)."""
    result = conn.execute(
        text(
            """
            UPDATE chat_messages
            SET tool_calls = CAST(:tool_calls AS JSONB),
                citations = CAST(:citations AS JSONB),
                updated_at = now()
            WHERE id = :message_id
            """
        ),
        {
            "message_id": message_id,
            "tool_calls": json.dumps(tool_calls) if tool_calls is not None else None,
            "citations": json.dumps(citations) if citations is not None else None,
        },
    )
    return result.rowcount


def mark_stale_streaming_attempts_for_conversation(conn, conversation_id: int, stale_before: datetime) -> int:
    """Step 12 Sub-step 3C: read-time stale-recovery, scoped to one
    conversation and called explicitly by the route before it reads
    (docs/step12_substep3c_plan.md section 3) -- deliberately NOT hidden
    inside get_conversation_with_active_messages, which stays a pure read
    with no side effects. Idempotent: the WHERE status='streaming' guard
    is the same mechanism finalize_assistant_message already relies on,
    so a message a concurrent request is genuinely still finalizing can
    never be double-transitioned by this call. stale_before is computed
    and passed in by the caller (not "now() - interval" computed here) so
    tests can supply a deterministic cutoff without waiting."""
    result = conn.execute(
        text(
            """
            UPDATE chat_messages
            SET status = 'failed',
                error_message = 'stale_streaming',
                completed_at = now(),
                updated_at = now()
            WHERE conversation_id = :conversation_id
              AND status = 'streaming'
              AND created_at < :stale_before
            """
        ),
        {"conversation_id": conversation_id, "stale_before": stale_before},
    )
    return result.rowcount


def mark_stale_streaming_messages_as_failed(conn) -> int:
    """Mark every message still 'streaming' as 'failed'. When/how often
    this is invoked (e.g. once at backend startup) is lifecycle wiring for
    a later Step 12 sub-step -- this function only implements the query
    itself. Returns rows affected."""
    result = conn.execute(
        text(
            """
            UPDATE chat_messages
            SET status = 'failed',
                error_message = 'interrupted by server restart',
                completed_at = now(),
                updated_at = now()
            WHERE status = 'streaming'
            """
        )
    )
    return result.rowcount
