/** A handful of stroke icons (24×24), inline so the app has no icon dependency. */
const PATHS: Record<string, string> = {
  pill: "M10.5 3.5a5 5 0 0 1 7 7l-7 7a5 5 0 0 1-7-7l7-7Z M8.5 8.5l7 7",
  pulse: "M3 12h4l2-5 4 10 2-5h6",
  calendar: "M4 6h16v14H4z M4 10h16 M8 3v4 M16 3v4",
  message: "M4 5h16v11H8l-4 4z",
  question: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .9-1 1.7 M12 17h.01",
  wifi: "M2 9a15 15 0 0 1 20 0 M5 12.5a10 10 0 0 1 14 0 M8.5 16a5 5 0 0 1 7 0 M12 20h.01",
  wifiOff: "M2 2l20 20 M8.5 16a5 5 0 0 1 7 0 M5 12.5a10 10 0 0 1 5-2.7 M2 9a15 15 0 0 1 4.5-3 M14 9.3a10 10 0 0 1 5 3.2 M12 20h.01",
  sync: "M20 11a8 8 0 0 0-14.5-4.5L4 8 M4 4v4h4 M4 13a8 8 0 0 0 14.5 4.5L20 16 M20 20v-4h-4",
  alert: "M12 3 2 20h20L12 3Z M12 9v5 M12 17h.01",
  phone: "M5 3h4l2 5-2.5 1.5a11 11 0 0 0 6 6L16 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 5a2 2 0 0 1 2-2Z",
  shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3Z M9 12l2 2 4-4",
  send: "M4 12 20 4l-6 16-3-7-7-1Z",
  x: "M6 6l12 12 M18 6 6 18",
  chevron: "M9 6l6 6-6 6",
  link: "M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1 M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1",
};

export function Icon({ name, size = 18 }: { name: keyof typeof PATHS | string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {(PATHS[name] ?? "").split(" M").map((d, i) => <path key={i} d={i === 0 ? d : `M${d}`} />)}
    </svg>
  );
}

export const TOOL_ICON: Record<string, string> = {
  record_medication: "pill", record_symptom: "pulse", book_appointment: "calendar", notify_family: "message",
  ask_pharmacist: "question",
};
