import "server-only";

import { NextRequest, NextResponse } from "next/server";

import {
  ApiError,
  archiveConversation,
  getConversation,
  updateConversation,
} from "@/lib/api/client";
import type { RoleMode } from "@/lib/api/types";

type RouteParams = { params: Promise<{ id: string }> };

export async function GET(_request: NextRequest, { params }: RouteParams) {
  const { id } = await params;
  try {
    const detail = await getConversation(Number(id));
    return NextResponse.json(detail);
  } catch (error) {
    if (error instanceof ApiError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }
    return NextResponse.json({ detail: (error as Error).message }, { status: 502 });
  }
}

export async function PATCH(request: NextRequest, { params }: RouteParams) {
  const { id } = await params;
  let payload: { title?: string | null; role_mode?: RoleMode | null };
  try {
    payload = (await request.json()) as { title?: string | null; role_mode?: RoleMode | null };
  } catch {
    return NextResponse.json({ detail: "request body must be valid JSON" }, { status: 400 });
  }

  try {
    const conversation = await updateConversation(Number(id), payload);
    return NextResponse.json(conversation);
  } catch (error) {
    if (error instanceof ApiError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }
    return NextResponse.json({ detail: (error as Error).message }, { status: 502 });
  }
}

export async function DELETE(_request: NextRequest, { params }: RouteParams) {
  const { id } = await params;
  try {
    await archiveConversation(Number(id));
    return NextResponse.json({ archived: true });
  } catch (error) {
    if (error instanceof ApiError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }
    return NextResponse.json({ detail: (error as Error).message }, { status: 502 });
  }
}
