export const DEVICES = [
  { id: "apple-health", name: "Apple Health", icon: "heart" },
  { id: "oura", name: "Oura", icon: "ring" },
  { id: "fitbit", name: "Fitbit", icon: "activity" },
  { id: "garmin", name: "Garmin", icon: "watch" },
  { id: "whoop", name: "WHOOP", icon: "band" },
  { id: "health-connect", name: "Google Fit / Health Connect", icon: "phone" },
] as const;
export type DeviceId = (typeof DEVICES)[number]["id"];
