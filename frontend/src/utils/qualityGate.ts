import type { QualityGateProvider } from "../services/api";

export const normalizeQualityGateProvider = (
  value?: string | null
): QualityGateProvider => {
  if (value === "github" || value === "gitlab" || value === "generic") {
    return value;
  }
  return "generic";
};
