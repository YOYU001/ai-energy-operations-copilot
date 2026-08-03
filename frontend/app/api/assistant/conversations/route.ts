import "server-only";

import { NextRequest, NextResponse } from "next/server";

import { ApiError, createConversation, getConversations } from "@/lib/api/client";
import type { RoleMode } from "@/lib/api/types";

// Step 12 Frontend Slice 1: thin JSON proxy (no streaming here) so a
// client component can reach the server-only lib/api/client.ts functions
// without ever knowing API_BASE_URL. Browser never calls FastAPI
// directly (docs/step12_frontend_chat_ui_plan.md section 1).

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const limitParam = searchParams.get("limit");
  const offsetParam = searchParams.get("offset");
  const limit = limitParam !== null ? Number(limitParam) : undefined;
  const offset = offsetParam !== null ? Number(offsetParam) : undefined;

  try {
    const page = await getConversations(limit, offset);
    return NextResponse.json(page);
  } catch (error) {
    if (error instanceof ApiError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }
    return NextResponse.json({ detail: (error as Error).message }, { status: 502 });
  }
}

export async function POST(request: NextRequest) {
  let roleMode: RoleMode | null | undefined;
  try {
    const body = (await request.json()) as { role_mode?: RoleMode | null };
    roleMode = body.role_mode;
  } catch {
    return NextResponse.json({ detail: "request body must be valid JSON" }, { status: 400 });
  }

  try {
    const conversation = await createConversation(roleMode ?? null);
    return NextResponse.json(conversation, { status: 201 });
  } catch (error) {
    if (error instanceof ApiError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }
    return NextResponse.json({ detail: (error as Error).message }, { status: 502 });
  }
}
