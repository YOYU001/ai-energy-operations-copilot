import "server-only";

import { NextRequest } from "next/server";

// Step 12 Frontend Slice 1: structurally identical to the message-send
// proxy (../route.ts) -- same passthrough contract, just no request body
// and the /regenerate path segment. See that file's comments for the
// full rationale (status/header/body/abort forwarding).
const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

type RouteParams = { params: Promise<{ id: string; messageId: string }> };

export async function POST(request: NextRequest, { params }: RouteParams) {
  const { id, messageId } = await params;

  let backendRes: Response;
  try {
    backendRes = await fetch(
      `${API_BASE_URL}/conversations/${id}/messages/${messageId}/regenerate`,
      {
        method: "POST",
        signal: request.signal,
      },
    );
  } catch (cause) {
    return new Response(
      JSON.stringify({ detail: `Failed to reach backend: ${(cause as Error).message}` }),
      { status: 502, headers: { "Content-Type": "application/json" } },
    );
  }

  if (!backendRes.ok) {
    // 400/404/409 established BEFORE any stream starts.
    return new Response(await backendRes.text(), {
      status: backendRes.status,
      headers: { "Content-Type": backendRes.headers.get("content-type") ?? "application/json" },
    });
  }

  return new Response(backendRes.body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
    },
  });
}
