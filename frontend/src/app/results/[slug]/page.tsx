import { notFound, unstable_rethrow } from "next/navigation";
import { api } from "@/lib/api";
import ResultsView from "@/components/ResultsView";

export const dynamic = "force-dynamic";

export default async function ResultsPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  let data;
  try {
    const topic = (await api.questions()).find((t) => t.slug === slug);
    if (!topic) notFound();
    const report = await api.ask(topic.question);
    data = { topic: { slug, label: topic.label, question: topic.question }, report };
  } catch (e) {
    unstable_rethrow(e);   // let notFound() through; anything else is an API failure
    return <p className="pt-24 text-center text-muted">The research service is unreachable. Start it with <code>make api</code>.</p>;
  }
  return <ResultsView {...data} />;
}
