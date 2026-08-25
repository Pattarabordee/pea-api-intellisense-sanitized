import type { Metadata } from "next";
import { getBuengKanTesterCatalog } from "../../lib/buengkan-resolver";
import { BuengKanTester } from "./tester-client";

export const metadata: Metadata = {
  title: "PEA Intellisense · Bueng Kan GIS Tester",
  description: "Shadow-mode village to feeder/transformer topology tester for Bueng Kan"
};

export default function BuengKanTesterPage() {
  const catalog = getBuengKanTesterCatalog();
  return <BuengKanTester catalog={catalog} />;
}
