import { api } from "@/lib/api";
import SearchView from "@/components/SearchView";

export const dynamic = "force-dynamic";

export default async function SearchPage() {
  let topics;
  try { topics = await api.questions(); } catch {
    return <p className="pt-24 text-center text-muted">The research service is unreachable. Start it with <code>make api</code>.</p>;
  }
  return <SearchView topics={topics.flatMap((t) => (t.slug ? [{ ...t, slug: t.slug }] : []))} />;
}
