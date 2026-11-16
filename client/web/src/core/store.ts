import type { ActionRow } from "./planner";

/** The outbox and a small key-value table. IndexedDB in the browser, in memory in tests. */
export interface Store {
  all(): Promise<ActionRow[]>;
  /** A whole plan in one transaction: an app kill between "planned" and "sent" never loses half a plan. */
  insertAll(rows: ActionRow[]): Promise<void>;
  update(row: ActionRow): Promise<void>;
  get(key: string): Promise<string | undefined>;
  put(key: string, value: string): Promise<void>;
}

const byPlanOrder = (a: ActionRow, b: ActionRow) => a.createdAtMs - b.createdAtMs || a.stepIndex - b.stepIndex;

export class MemoryStore implements Store {
  private rows = new Map<string, ActionRow>();
  private kv = new Map<string, string>();
  async all() { return [...this.rows.values()].map((r) => ({ ...r })).sort(byPlanOrder); }
  async insertAll(rows: ActionRow[]) {
    for (const r of rows) if ([...this.rows.values()].some((x) => x.stepKey === r.stepKey)) throw new Error("duplicate step_key");
    for (const r of rows) this.rows.set(r.actionId, { ...r });
  }
  async update(row: ActionRow) { this.rows.set(row.actionId, { ...row }); }
  async get(key: string) { return this.kv.get(key); }
  async put(key: string, value: string) { this.kv.set(key, value); }
}

export class IdbStore implements Store {
  private constructor(private db: IDBDatabase) {}

  static open(name = "medsync"): Promise<IdbStore> {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(name, 1);
      request.onupgradeneeded = () => {
        const db = request.result;
        const outbox = db.createObjectStore("outbox", { keyPath: "actionId" });
        outbox.createIndex("stepKey", "stepKey", { unique: true });
        db.createObjectStore("kv");
      };
      request.onsuccess = () => resolve(new IdbStore(request.result));
      request.onerror = () => reject(request.error);
    });
  }

  private run<T>(stores: string[], mode: IDBTransactionMode, body: (tx: IDBTransaction) => IDBRequest<T> | void):
    Promise<T | undefined> {
    return new Promise((resolve, reject) => {
      const tx = this.db.transaction(stores, mode);
      const request = body(tx);
      tx.oncomplete = () => resolve(request ? request.result : undefined);
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  }

  async all() {
    const rows = await this.run<ActionRow[]>(["outbox"], "readonly", (tx) => tx.objectStore("outbox").getAll());
    return (rows ?? []).sort(byPlanOrder);
  }
  async insertAll(rows: ActionRow[]) {
    await this.run(["outbox"], "readwrite", (tx) => { for (const r of rows) tx.objectStore("outbox").add(r); });
  }
  async update(row: ActionRow) {
    await this.run(["outbox"], "readwrite", (tx) => { tx.objectStore("outbox").put(row); });
  }
  async get(key: string) {
    return (await this.run<string>(["kv"], "readonly", (tx) => tx.objectStore("kv").get(key))) ?? undefined;
  }
  async put(key: string, value: string) {
    await this.run(["kv"], "readwrite", (tx) => { tx.objectStore("kv").put(value, key); });
  }
}
