import { describe, expect, it } from "vitest";
import type { GatewayApi, SubmitResult } from "./gateway";
import { plan, type ActionRow } from "./planner";
import { detect } from "./redflag";
import { date, route } from "./router";
import { next } from "./state";
import { canonical, stepKey } from "./stepKey";
import { MemoryStore } from "./store";
import { SyncEngine, backoffMs } from "./sync";

describe("step_key", () => {
  it("matches the Kotlin client byte for byte (same vectors as OutboxTest.kt)", async () => {
    expect(await stepKey("device-1", "plan-1", 0, "book_appointment", { patient_id: "self", department: "消化内科", date: "2026-11-18" }))
      .toBe("859400be70f2b074c571f6497d0bb03702f495233f6a32de3aed19ac042fec1e");
    expect(await stepKey("device-1", "plan-1", 1, "record_medication", { takenAt: 1763280000000, name: "布洛芬" }))
      .toBe("747011280527089efabd7314b4e648f865d5e5d993b5b53c50f1fd8af7c7b137");
    expect(await stepKey("d", "p", 2, "notify_family", { to: "女儿 \"老大\"\n" }))
      .toBe("b963287cedff260e943188c66c0f0542ea167609ba34594157a4497a4bd00e89");
  });

  it("canonical JSON ignores key order", () => {
    expect(canonical({ b: 1, a: { d: [1, "x"], c: null } })).toBe(canonical({ a: { c: null, d: [1, "x"] }, b: 1 }));
  });

  it("free text is not part of the identity: a reworded note keeps the key", async () => {
    const a = await plan([{ tool: "book_appointment", payload: { patient_id: "self", department: "全科", date: "2026-11-18", note: "复诊" } }], "d", 0, "", "p");
    const b = await plan([{ tool: "book_appointment", payload: { patient_id: "self", department: "全科", date: "2026-11-18", note: "复诊（重试）" } }], "d", 0, "", "p");
    expect(a[0].stepKey).toBe(b[0].stepKey);
  });
});

describe("rule router (port of RuleRouter.kt)", () => {
  const monday = "2026-11-16";
  it("splits a compound sentence into a dependency graph", () => {
    const r = route("我吃了布洛芬，有点胃疼，帮我约周三复诊，告诉女儿", monday, 0);
    expect(r.steps.map((s) => s.tool)).toEqual(["record_medication", "record_symptom", "book_appointment", "notify_family"]);
    expect(r.steps[2].payload).toMatchObject({ department: "消化内科", date: "2026-11-18" });
    expect(r.steps[2].dependsOn).toEqual([1]);
    expect(r.steps[3].dependsOn).toEqual([0, 1]);
  });
  it("routes questions to the pharmacist only", () => {
    const r = route("布洛芬能和阿司匹林一起吃吗？", monday, 0);
    expect(r.question).toBe(true);
    expect(r.steps.map((s) => s.tool)).toEqual(["ask_pharmacist"]);
  });
  it("reads dates the same way as the Kotlin parser", () => {
    expect(date("约一下周二复诊", monday)).toBe("2026-11-17");
    expect(date("约下周二复诊", monday)).toBe("2026-11-24");
    expect(date("后天", monday)).toBe("2026-11-18");
    expect(date("1月3日复诊", monday)).toBe("2027-01-03");
  });
});

describe("red flags", () => {
  it("respects negation and gives self-harm the hotline", () => {
    expect(detect("突然胸口痛得厉害")?.matched).toBe("胸口痛");
    expect(detect("今天没有胸痛，只是有点胃疼")).toBeUndefined();
    expect(detect("吃了一整瓶药，不想活了")?.kind).toBe("CRISIS");
    expect(detect("药吃多了，想解脱")?.kind).toBe("CRISIS");
  });
});

describe("state machine", () => {
  it("allows the documented transitions only", () => {
    expect(next("PENDING", "Send")).toBe("SENDING");
    expect(next("ACKED", "TransientError")).toBe("ACKED");
    expect(() => next("DONE", "Send")).toThrow();
  });
});

class FakeApi implements GatewayApi {
  calls: string[] = [];
  constructor(public answer: (row: ActionRow) => SubmitResult = () => ({ kind: "Done", result: null })) {}
  async submit(row: ActionRow) { this.calls.push(row.tool); return this.answer(row); }
  async status() { return { kind: "Done", result: null } as SubmitResult; }
  async resume() { return { kind: "Done", result: { ok: true } } as SubmitResult; }
}

async function setup(api: FakeApi, text = "我吃了布洛芬，有点胃疼，帮我约周三复诊，告诉女儿") {
  const store = new MemoryStore();
  await store.insertAll(await plan(route(text, "2026-11-16", 0).steps, "dev", 0, text));
  return { store, engine: new SyncEngine(store, api, () => 0.5) };
}

describe("sync engine (port of SyncEngine.kt)", () => {
  it("sends in dependency order and unblocks children in the same pass", async () => {
    const api = new FakeApi();
    const { store, engine } = await setup(api);
    const report = await engine.drainOnce(0);
    expect(api.calls).toEqual(["record_medication", "record_symptom", "book_appointment", "notify_family"]);
    expect(report).toMatchObject({ sent: 4, done: 4 });
    expect((await store.all()).every((r) => r.state === "DONE")).toBe(true);
  });

  it("keeps the same step_key across retries after a network error", async () => {
    let offline = true;
    const keys: string[] = [];
    const api = new FakeApi((row) => { keys.push(row.stepKey); return offline ? { kind: "Transient", message: "timeout" } : { kind: "Done", result: null }; });
    const { store, engine } = await setup(api, "帮我约明天的心内科");
    await engine.drainOnce(0);
    expect((await store.all())[0]).toMatchObject({ state: "RETRY_WAIT", attempt: 1 });
    offline = false;
    await engine.drainOnce(backoffMs(0, () => 0.5) + 1);
    expect((await store.all())[0].state).toBe("DONE");
    expect(new Set(keys).size).toBe(1);
  });

  it("a failed parent asks the user instead of sending its children", async () => {
    const api = new FakeApi((row) => row.tool === "record_symptom" ? { kind: "Failed", reason: "rejected" } : { kind: "Done", result: null });
    const { store, engine } = await setup(api, "有点胃疼，帮我约周三复诊");
    await engine.drainOnce(0);
    const rows = await store.all();
    expect(rows.map((r) => r.state)).toEqual(["FAILED", "NEEDS_USER"]);
    expect(rows[1].reason).toBe("parent_not_done");
    expect(api.calls).toEqual(["record_symptom"]);
  });

  it("a whole plan is stored in one go; a reused step_key is refused", async () => {
    const store = new MemoryStore();
    const rows = await plan([{ tool: "notify_family", payload: { to: "女儿", message: "hi" } }], "d", 0, "", "p");
    await store.insertAll(rows);
    await expect(store.insertAll(rows.map((r) => ({ ...r, actionId: "other" })))).rejects.toThrow();
  });
});
