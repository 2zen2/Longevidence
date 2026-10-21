import raw from "./mock_users.json";

export interface Patient {
  id: string; name: string; age: number; sex: string; profileType: string;
  healthMetrics: Record<string, number | string>;
  medicalHistory: string[];
  medications: { name: string; dose: string; reason: string }[];
  supplements: { name: string; dose: string; reason: string }[];
  lifestyle: Partial<Record<string, string | number | string[]>>;
  healthInterests: string[];
  relevantQuestions: string[];
}

export const PATIENTS: Patient[] = raw.patients as Patient[];
export const getPatient = (id: string | null | undefined) => PATIENTS.find((p) => p.id === id) ?? null;
export const initials = (name: string) => name.split(" ").map((w) => w[0]).join("").slice(0, 2);
