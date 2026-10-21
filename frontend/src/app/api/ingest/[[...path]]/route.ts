// Pass-through so the browser can drive topic ingestion; the API itself stays server-side only.
// INGEST_UI=off disables it (public demos). INGEST_TOKEN, when set, is sent to the API as X-Ingest-Token.
const BASE = process.env.API_URL ?? "http://localhost:8010";
const MAX_BODY = 4096;

async function forward(req: Request, ctx: { params: Promise<{ path?: string[] }> }) {
  if (process.env.INGEST_UI === "off") return new Response("Not found", { status: 404 });
  const path = (await ctx.params).path ?? [];
  const known = req.method === "POST" ? path.length === 0 || (path.length === 1 && path[0] === "plan")
    : path.length === 1 && (path[0] === "status" || /^\d+$/.test(path[0]));
  if (!known) return new Response("Not found", { status: 404 });
  const body = req.method === "POST" ? await req.text() : undefined;
  if (body && body.length > MAX_BODY) return new Response("Too large", { status: 413 });
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (process.env.INGEST_TOKEN) headers["x-ingest-token"] = process.env.INGEST_TOKEN;
  const res = await fetch(`${BASE}/api/ingest${path.length ? "/" + path.join("/") : ""}`, { method: req.method, body, cache: "no-store", headers });
  return new Response(await res.text(), { status: res.status, headers: { "content-type": "application/json" } });
}
export { forward as GET, forward as POST };
