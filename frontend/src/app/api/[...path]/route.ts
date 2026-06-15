/**
 * Catch-all proxy: forwards `/api/*` to the FastAPI backend.
 *
 * Used for the auth, chat, and JSON endpoints where axios sets the auth
 * header. For multipart uploads (face / voice) and for streaming audio/video
 * the file is piped through. For large media, see `/api/media/[...]` for a
 * dedicated stream.
 */
import { NextRequest, NextResponse } from "next/server";

const BACKEND = process.env.API_INTERNAL_URL || "http://localhost:8000/api/v1";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

async function forward(req: NextRequest) {
  const url = new URL(req.url);
  const path = url.pathname.replace(/^\/api/, "");
  const target = `${BACKEND}${path}${url.search}`;

  const headers = new Headers();
  for (const [k, v] of req.headers) {
    if (["host", "connection", "content-length"].includes(k.toLowerCase())) continue;
    headers.set(k, v);
  }

  const init: RequestInit = {
    method: req.method,
    headers,
    body: ["GET", "HEAD"].includes(req.method) ? undefined : req.body,
    // @ts-expect-error duplex is required for streaming bodies in undici
    duplex: "half",
  };

  const res = await fetch(target, init);
  const out = new NextResponse(res.body, { status: res.status });
  res.headers.forEach((v, k) => {
    if (k.toLowerCase() === "content-encoding") return;
    out.headers.set(k, v);
  });
  return out;
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;
