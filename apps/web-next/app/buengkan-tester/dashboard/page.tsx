import { getBuengKanTesterCatalog } from "../../../lib/buengkan-resolver";
import { BuengKanFeedbackDashboard } from "./dashboard-client";

export const dynamic = "force-static";

export default function BuengKanFeedbackDashboardPage() {
  return <BuengKanFeedbackDashboard catalog={getBuengKanTesterCatalog()} />;
}
