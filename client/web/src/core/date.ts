/** A calendar date without time or zone (kotlinx LocalDate), as "YYYY-MM-DD". */
export type LocalDate = string;

export function today(nowMs: number = Date.now()): LocalDate {
  const d = new Date(nowMs);
  return fmt(d.getFullYear(), d.getMonth() + 1, d.getDate());
}

export function plusDays(date: LocalDate, days: number): LocalDate {
  const [y, m, d] = date.split("-").map(Number);
  const t = new Date(Date.UTC(y, m - 1, d + days));
  return fmt(t.getUTCFullYear(), t.getUTCMonth() + 1, t.getUTCDate());
}

/** ISO day number: Monday 1 … Sunday 7. */
export function isoDay(date: LocalDate): number {
  const [y, m, d] = date.split("-").map(Number);
  const day = new Date(Date.UTC(y, m - 1, d)).getUTCDay();
  return day === 0 ? 7 : day;
}

export function fmt(y: number, m: number, d: number): LocalDate {
  return `${String(y).padStart(4, "0")}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}
