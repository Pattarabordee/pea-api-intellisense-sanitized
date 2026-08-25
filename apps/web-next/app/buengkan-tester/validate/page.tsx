import type { Metadata } from "next";
import { BuengKanFieldValidation } from "./validation-client";

export const metadata: Metadata = {
  title: "PEA Intellisense · Bueng Kan Field Validation",
  description: "Shadow-mode field validation for POI and road/soi transformer candidates"
};

export default function BuengKanFieldValidationPage() {
  return <BuengKanFieldValidation />;
}
