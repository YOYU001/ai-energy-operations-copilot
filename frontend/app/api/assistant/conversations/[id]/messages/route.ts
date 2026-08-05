import "server-only";

import { NextRequest, NextResponse } from "next/server";

import { ApiError, getConversationMessages } from "@/lib/api/client";

// Step 12 Frontend Slice 1. Same server-only API_BASE_URL as
// lib/api/client.ts -- redefined locally here (not exported from that
// module) because the POST handler below deliberately bypasses apiFetch:
// apiFetch hardcodes res.json() and a 5s AbortSignal.timeout, both wrong
// for a long-lived SSE response (docs/step12_frontend_chat_ui_plan.md
// section 1).
const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

type RouteParams = { params: Promise<{ id: string }> };

export async function GET(_request: NextRequest, { params }: RouteParams) {
  const { id } = await params;
  try {
    const messages = await getConversationMessages(Number(id));
    return NextResponse.json(messages);
  } catch (error) {
    if (error instanceof ApiError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }
    return NextResponse.json({ detail: (error as Error).message }, { status: 502 });
  }
}

export async function POST(request: NextRequest, { params }: RouteParams) {
  const { id } = await params;
  const body = await request.text(); // raw JSON passthrough, no re-parsing needed

  let backendRes: Response;
  try {
    backendRes = await fetch(`${API_BASE_URL}/conversations/${id}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      signal: request.signal, // client abort -> this fetch aborts -> backend observes disconnect
    });
  } catch (cause) {
    return NextResponse.json(
      { detail: `Failed to reach backend: ${(cause as Error).message}` },
      { status: 502 },
    );
  }

  if (!backendRes.ok) {
    // 400/404 established BEFORE any stream starts -- plain HTTP error
    // passthrough, no SSE framing involved at all.
    return new Response(await backendRes.text(), {
      status: backendRes.status,
      headers: { "Content-Type": backendRes.headers.get("content-type") ?? "application/json" },
    });
  }

  // Stream established -- passthrough the body untouched, no re-framing
  // of SSE events in this proxy layer. Any failure from this point on is
  // communicated via a message_failed SSE event inside the stream
  // itself, never a changed HTTP status (matches the backend contract:
  // once StreamingResponse is returned, every outcome is a data-plane
  // event, not a status-code change).
  return new Response(backendRes.body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
    },
  });
}
