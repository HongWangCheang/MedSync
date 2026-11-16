import { today } from "./date";
import { FetchGatewayApi, type GatewayApi } from "./gateway";
import { plan, type ActionRow } from "./planner";
import { detect, type RedFlag } from "./redflag";
import { followUp, type Choice, type Decision, type PharmacistAnswer, choiceTitle } from "./results";
import { route, type StepDraft } from "./router";
import { next } from "./state";
import { IdbStore, type Store } from "./store";
import { SyncEngine, type DrainReport } from "./sync";
import type { Json } from "./stepKey";

export interface Snapshot {
  rows: ActionRow[];
  offline: boolean;
  redFlag?: RedFlag;
  notice?: string;
  lastSync?: { report: DrainReport; atMs: number };
  syncing: boolean;
}

export const SAVED_OFFLINE = "已保存在本机，联网后自动同步";

/**
 * Everything the page needs (a port of app/MedSyncController.kt): danger signs first, then the rule router, the
 * plan into the outbox in one transaction, and a drain when online. "离线（模拟）" stops all traffic to the gateway,
 * like the switch in the apps; a real loss of network is handled the same way by the sync engine's retries.
 */
export class Controller {
  private snapshot: Snapshot = { rows: [], offline: false, syncing: false };
  private listeners = new Set<() => void>();
  private engine: SyncEngine;

  constructor(private store: Store, api: GatewayApi, private clock: () => number = Date.now) {
    this.engine = new SyncEngine(store, api);
  }

  static async open(): Promise<Controller> {
    const store = await IdbStore.open();
    const api = new FetchGatewayApi("", () => store.get("token").then((t) => t || undefined), (t) => store.put("token", t));
    const controller = new Controller(store, api);
    controller.snapshot.offline = (await store.get("offline")) === "1";
    await controller.refresh();
    return controller;
  }

  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => this.listeners.delete(listener); };
  getSnapshot = () => this.snapshot;

  private set(change: Partial<Snapshot>) {
    this.snapshot = { ...this.snapshot, ...change };
    this.listeners.forEach((l) => l());
  }

  private async refresh() { this.set({ rows: await this.store.all() }); }

  private async deviceId(): Promise<string> {
    const saved = await this.store.get("device_id");
    if (saved) return saved;
    const id = crypto.randomUUID();
    await this.store.put("device_id", id);
    return id;
  }

  async submit(text: string): Promise<void> {
    const input = text.trim();
    if (!input) return;
    this.set({ redFlag: detect(input), notice: undefined });
    const now = this.clock();
    const conversation = followUp(this.snapshot.rows, now);
    let { steps, question } = route(input, today(now), now);
    if (steps.length === 0 && conversation?.awaitingChoice) {
      // The pharmacist asked "which product?"; a bare reply like "ADVIL" answers that question.
      steps = [{ tool: "ask_pharmacist", payload: { question: input } }];
      question = true;
    }
    if (question && conversation?.sessionId) {
      steps = [{ ...steps[0], payload: { ...steps[0].payload, session_id: conversation.sessionId } }];
    }
    if (steps.length === 0) {
      if (!this.snapshot.redFlag) this.set({ notice: "没有识别出要做的事。可以试试：“我吃了布洛芬，有点胃疼，帮我约周三复诊”" });
      return;
    }
    if (question && this.snapshot.offline) {
      this.set({ notice: "用药问答需要联网检索说明书。离线时不回答，避免给出没有依据的建议。" });
      return;
    }
    await this.enqueue(steps, input);
  }

  /** The user tapped one of the products the pharmacist offered. */
  async choose(answer: PharmacistAnswer, choice: Choice): Promise<void> {
    if (this.snapshot.offline) return this.set({ notice: "用药问答需要联网检索说明书。" });
    const payload: { [key: string]: Json } = {
      question: `我选：${choiceTitle(choice)}`,
      selection: { label_id: choice.labelId, version: choice.version },
      ...(answer.sessionId ? { session_id: answer.sessionId } : {}),
    };
    await this.enqueue([{ tool: "ask_pharmacist", payload }], `我选：${choiceTitle(choice)}`);
  }

  private async enqueue(steps: StepDraft[], utterance: string) {
    const now = this.clock();
    await this.store.insertAll(await plan(steps, await this.deviceId(), now, utterance));
    this.set({ notice: this.snapshot.offline ? SAVED_OFFLINE : undefined });
    await this.refresh();
    if (!this.snapshot.offline) await this.sync();
  }

  /** A server-side NEEDS_USER (with options) goes back through the gateway; a local cascade is cancelled locally. */
  async resolve(row: ActionRow, decision: Decision | null): Promise<void> {
    if (decision === null) {
      await this.store.update({ ...row, state: next(row.state, "Cancelled"), reason: "cancelled_by_user" });
      return this.refresh();
    }
    if (this.snapshot.offline) return this.set({ notice: "需要联网才能提交你的选择" });
    await this.engine.resolve(row, decision as { [key: string]: Json }, this.clock());
    await this.refresh();
    await this.sync();
  }

  async setOffline(offline: boolean): Promise<void> {
    await this.store.put("offline", offline ? "1" : "0");
    this.set({ offline, notice: !offline && this.snapshot.notice === SAVED_OFFLINE ? undefined : this.snapshot.notice });
    if (!offline) await this.sync();
  }

  async sync(): Promise<void> {
    if (this.snapshot.offline || this.snapshot.syncing) return;
    this.set({ syncing: true });
    try {
      const report = await this.engine.drainOnce(this.clock());
      this.set({ lastSync: { report, atMs: this.clock() } });
    } catch (error) {
      this.set({ notice: `同步出错：${error instanceof Error ? error.message : String(error)}` });
    } finally {
      await this.refresh();
      this.set({ syncing: false });
    }
  }

  dismissRedFlag() { this.set({ redFlag: undefined }); }

  /** A timer, plus the browser's own "back online" signal. */
  start(intervalMs = 5_000): () => void {
    const timer = setInterval(() => void this.sync(), intervalMs);
    const online = () => void this.sync();
    window.addEventListener("online", online);
    void this.sync();
    return () => { clearInterval(timer); window.removeEventListener("online", online); };
  }
}
