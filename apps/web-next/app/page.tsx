import { IncidentPriorityQueue } from "./incident-priority-queue";
import { incidentPriorityDemo } from "../lib/incident-priority";

export default function Page() {
  return <IncidentPriorityQueue snapshot={incidentPriorityDemo} />;
}
