import { IncidentPriorityQueue } from "../incident-priority-queue";
import { loadIncidentQueueFeed } from "../../lib/incident-queue-feed";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export default async function IncidentPriorityPage() {
  const { snapshot, source_health } = await loadIncidentQueueFeed();
  return <IncidentPriorityQueue snapshot={snapshot} sourceHealth={source_health} />;
}
