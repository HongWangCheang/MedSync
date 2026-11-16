/**
 * The logical identity of a planned step, generated at planning time and stored before anything is sent.
 * Byte-for-byte the same as the Kotlin client (outbox/StepKey.kt): sha256 of
 * "deviceId|planId|stepIndex|tool|canonical(identityArgs)", so web and phones share the gateway's ledger semantics.
 */
export type Json = string | number | boolean | null | Json[] | { [key: string]: Json };

/** JSON with object keys sorted at every level (kotlinx JsonPrimitive formatting for strings and numbers). */
export function canonical(value: Json): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (typeof value === "object") {
    return `{${Object.keys(value).sort(compareKeys).map((k) => `${JSON.stringify(k)}:${canonical(value[k])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

/** Kotlin sorts keys by String.compareTo: UTF-16 code units, the same as this. */
function compareKeys(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

export async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

export function stepKey(deviceId: string, planId: string, stepIndex: number, tool: string,
                        identityArgs: { [key: string]: Json }): Promise<string> {
  return sha256Hex(`${deviceId}|${planId}|${stepIndex}|${tool}|${canonical(identityArgs)}`);
}
