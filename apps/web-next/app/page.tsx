import { MissionControl } from "./mission-control";
import { demoOperatorData } from "../lib/demo-data";

export default function Page() {
  return <MissionControl initialData={{ ...demoOperatorData, source: "DEMO DATA - synthetic only" }} />;
}
