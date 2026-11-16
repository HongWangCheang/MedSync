import type { ActionRow } from "./planner";
import type { Json } from "./stepKey";

/** What hop ① can answer. Transient means "nothing is known; try again later with the same step_key". */
export type SubmitResult =
  | { kind: "Done"; result: Json | null }
  | { kind: "Accepted" }
  | { kind: "NeedsUser"; reason: string | null; result: Json | null }
  | { kind: "Failed"; reason: string | null }
  | { kind: "Cancelled"; reason: string | null }
  | { kind: "Conflict" }
  | { kind: "Transient"; message: string };

export interface GatewayApi {
  submit(action: ActionRow): Promise<SubmitResult>;
  status(stepKey: string): Promise<SubmitResult>;
  resume(stepKey: string, decision: { [key: string]: Json }): Promise<SubmitResult>;
}

interface View { stepKey: string; status: string; result?: Json | null; reason?: string | null }

/**
 * fetch client for the gateway (mirrors sync/GatewayApi.kt). A development account is registered on first use and
 * its token kept in the store, so the demo works out of the box; a real app needs a proper login.
 */
export class FetchGatewayApi implements GatewayApi {
  constructor(
    private baseUrl: string,
    private loadToken: () => Promise<string | undefined>,
    private saveToken: (token: string) => Promise<void>,
    private timeoutMs = 20_000,
  ) {}

  submit(action: ActionRow) {
    return this.call((auth) => this.request("POST", "/v1/actions", auth, wire(action)));
  }
  status(stepKey: string) {
    return this.call((auth) => this.request("GET", `/v1/actions/${stepKey}`, auth));
  }
  resume(stepKey: string, decision: { [key: string]: Json }) {
    return this.call((auth) => this.request("POST", `/v1/actions/${stepKey}/resume`, auth, decision));
  }

  private async request(method: string, path: string, token: string | null, body?: unknown): Promise<Response> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      return await fetch(this.baseUrl + path, {
        method,
        signal: controller.signal,
        headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } finally {
      clearTimeout(timer);
    }
  }

  private async token(): Promise<string> {
    const saved = await this.loadToken();
    if (saved) return saved;
    const response = await this.request("POST", "/v1/auth/register", null, {
      username: `web_${crypto.randomUUID().replaceAll("-", "").slice(0, 12)}`,
      password: crypto.randomUUID(),
    });
    if (response.status !== 201) throw new Error(`register failed: HTTP ${response.status}`);
    const { token } = (await response.json()) as { token: string };
    await this.saveToken(token);
    return token;
  }

  private async call(send: (token: string) => Promise<Response>): Promise<SubmitResult> {
    try {
      const response = await send(await this.token());
      const code = response.status;
      if (code === 200) return toResult((await response.json()) as View);
      if (code === 409) return { kind: "Conflict" };
      if (code === 401) {
        await this.saveToken("");
        return { kind: "Transient", message: "unauthorized" };
      }
      if (code === 429) return { kind: "Transient", message: "rate limited" };
      if (code >= 400 && code < 500) return { kind: "Failed", reason: `HTTP ${code}` };
      return { kind: "Transient", message: `HTTP ${code}` };
    } catch (error) {
      // Network down, DNS, abort on timeout: the outcome is unknown, retry later with the same step_key.
      return { kind: "Transient", message: error instanceof Error ? error.message : String(error) };
    }
  }
}

function toResult(view: View): SubmitResult {
  switch (view.status) {
    case "DONE": return { kind: "Done", result: view.result ?? null };
    case "ACCEPTED": return { kind: "Accepted" };
    case "NEEDS_USER": return { kind: "NeedsUser", reason: view.reason ?? null, result: view.result ?? null };
    case "CANCELLED": return { kind: "Cancelled", reason: view.reason ?? null };
    default: return { kind: "Failed", reason: view.reason ?? view.status };
  }
}

function wire(action: ActionRow) {
  return {
    stepKey: action.stepKey,
    planId: action.planId,
    stepIndex: action.stepIndex,
    tool: action.tool,
    toolClass: action.toolClass,
    identityArgs: JSON.parse(action.identityArgsJson),
    payload: JSON.parse(action.payloadJson),
    preconditions: JSON.parse(action.preconditionsJson),
    createdAtMs: action.createdAtMs,
    ...(action.expiresAtMs !== null ? { expiresAtMs: action.expiresAtMs } : {}),
  };
}
