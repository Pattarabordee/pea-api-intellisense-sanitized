"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import styles from "./dashboard.module.css";

type Catalog = {
  schemaVersion: number;
  supported: Array<{ key: string; name: string }>;
  excluded: Array<{ key: string; name: string }>;
};

type FeedbackItem = {
  receipt_id: string;
  recorded_at: string;
  query_hash: string;
  verdict: "CORRECT" | "INCORRECT" | "UNSURE";
  village_key: string;
  resolver_status: string;
  selected_feeder: string;
  transformer_candidates: string[];
  correction_feeder: string;
  correction_transformer: string;
};

type DashboardData = {
  mode: "shadow";
  production_send: "blocked";
  generated_at: string;
  count: number;
  items: FeedbackItem[];
  summary: {
    total: number;
    correct: number;
    incorrect: number;
    unsure: number;
    latest_at: string;
  };
};

type VillageStat = {
  key: string;
  name: string;
  total: number;
  correct: number;
  incorrect: number;
  unsure: number;
};

const verdictLabel = {
  CORRECT: "ถูกต้อง",
  INCORRECT: "ไม่ถูกต้อง",
  UNSURE: "ไม่แน่ใจ"
} as const;

function fmtTime(value: string) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("th-TH", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Bangkok"
  }).format(date);
}

function pct(value: number, total: number) {
  return total > 0 ? `${((value / total) * 100).toFixed(1)}%` : "—";
}

export function BuengKanFeedbackDashboard({ catalog }: { catalog: Catalog }) {
  const [accessCode, setAccessCode] = useState("");
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const saved = window.sessionStorage.getItem("bkDashboardAccessCode");
    if (saved) setAccessCode(saved);
  }, []);

  const names = useMemo(() => {
    const result = new Map<string, string>();
    for (const item of catalog.supported) result.set(item.key, item.name);
    for (const item of catalog.excluded) result.set(item.key, item.name);
    return result;
  }, [catalog]);

  const villageStats = useMemo<VillageStat[]>(() => {
    if (!data) return [];
    const map = new Map<string, VillageStat>();
    for (const item of data.items) {
      if (!item.village_key || item.village_key.startsWith("SMOKE-")) continue;
      const stat = map.get(item.village_key) ?? {
        key: item.village_key,
        name: names.get(item.village_key) ?? item.village_key,
        total: 0,
        correct: 0,
        incorrect: 0,
        unsure: 0
      };
      stat.total += 1;
      if (item.verdict === "CORRECT") stat.correct += 1;
      if (item.verdict === "INCORRECT") stat.incorrect += 1;
      if (item.verdict === "UNSURE") stat.unsure += 1;
      map.set(item.village_key, stat);
    }
    return [...map.values()].sort((a, b) => b.total - a.total || a.name.localeCompare(b.name, "th"));
  }, [data, names]);

  const reviewItems = useMemo(
    () => data?.items.filter((item) => item.verdict !== "CORRECT" && !item.village_key.startsWith("SMOKE-")).slice(0, 10) ?? [],
    [data]
  );

  const adjudicated = (data?.summary.correct ?? 0) + (data?.summary.incorrect ?? 0);

  async function load(event?: FormEvent) {
    event?.preventDefault();
    if (!accessCode.trim()) {
      setError("กรุณาใส่ Dashboard Access Code");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const response = await fetch("/api/buengkan/dashboard", {
        method: "POST",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ accessCode: accessCode.trim(), limit: 500 })
      });
      if (response.status === 401) {
        setData(null);
        setError("Dashboard Access Code ไม่ถูกต้อง");
        return;
      }
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "LOAD_FAILED");
      setData(payload as DashboardData);
      window.sessionStorage.setItem("bkDashboardAccessCode", accessCode.trim());
    } catch {
      setError("โหลดข้อมูล Dashboard ไม่สำเร็จ กรุณาลองใหม่");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className={styles.shell} lang="th">
      <header className={styles.topbar}>
        <a className={styles.brand} href="/buengkan-tester">
          <span className={styles.brandBlock}>PEA</span>
          <span><strong>INTELLISENSE</strong><small>BUENG KAN / FIELD VALIDATION</small></span>
        </a>
        <nav className={styles.nav} aria-label="Bueng Kan tester navigation">
          <a href="/buengkan-tester">TESTER</a>
          <span className={styles.navActive}>FEEDBACK</span>
        </nav>
        <span className={styles.live}><i /> SHADOW / LIVE</span>
      </header>

      <section className={styles.hero}>
        <div>
          <p className={styles.kicker}>FIELD TRUTH / 004</p>
          <h1>GIS mapping,<br />meet field truth.</h1>
          <p className={styles.lead}>Dashboard สำหรับติดตามว่า topology candidate ที่ระบบตอบให้ Tester บึงกาฬ ตรงกับความรู้หน้างานจริงมากน้อยแค่ไหน</p>
        </div>
        <div className={styles.heroPanel}>
          <span className={styles.panelIndex}>REGISTRY / V{catalog.schemaVersion}</span>
          <strong>{catalog.supported.length.toString().padStart(2, "0")}</strong>
          <p>SUPPORTED VILLAGES</p>
          <div className={styles.rule} />
          <span>POSTGRES LEDGER</span>
          <span>NO RAW QUERY / NO PII</span>
          <span>PRODUCTION SEND / BLOCKED</span>
        </div>
      </section>

      {!data && (
        <section className={styles.accessPanel}>
          <div className={styles.sectionLabel}><span>001</span><strong>CONTROL</strong></div>
          <form onSubmit={load} className={styles.accessForm}>
            <label htmlFor="dashboard-code">Dashboard Access Code</label>
            <div className={styles.accessRow}>
              <input id="dashboard-code" type="password" autoComplete="off" value={accessCode} onChange={(e) => setAccessCode(e.target.value)} placeholder="วาง Dashboard Access Code" />
              <button type="submit" disabled={loading}>{loading ? "LOADING…" : "OPEN DASHBOARD →"}</button>
            </div>
            {error && <p className={styles.error} role="alert">{error}</p>}
          </form>
        </section>
      )}

      {data && (
        <>
          <section className={styles.section}>
            <div className={styles.sectionLabel}><span>001</span><strong>OVERVIEW</strong><button type="button" onClick={() => load()} disabled={loading}>{loading ? "REFRESHING…" : "REFRESH ↻"}</button></div>
            {error && <p className={styles.error} role="alert">{error}</p>}
            <div className={styles.statGrid}>
              <article><span>TOTAL FEEDBACK</span><strong>{data.summary.total.toLocaleString("th-TH")}</strong><small>รายการสะสมใน Postgres</small></article>
              <article className={styles.good}><span>CONFIRMED CORRECT</span><strong>{pct(data.summary.correct, adjudicated)}</strong><small>{data.summary.correct} / {adjudicated || 0} adjudicated cases</small></article>
              <article className={styles.bad}><span>INCORRECT</span><strong>{data.summary.incorrect}</strong><small>ควรตรวจ mapping / clue</small></article>
              <article className={styles.warn}><span>UNSURE</span><strong>{data.summary.unsure}</strong><small>ต้องมีหลักฐานเพิ่ม</small></article>
            </div>
            <div className={styles.metaStrip}>
              <span>MODE <b>{data.mode.toUpperCase()}</b></span>
              <span>PRODUCTION SEND <b>{data.production_send.toUpperCase()}</b></span>
              <span>LATEST <b>{fmtTime(data.summary.latest_at)}</b></span>
              <span>LOADED <b>{data.count}</b></span>
            </div>
          </section>

          <section className={styles.section}>
            <div className={styles.sectionLabel}><span>002</span><strong>VILLAGE SIGNAL</strong></div>
            {villageStats.length === 0 ? (
              <div className={styles.empty}>ยังไม่มี feedback จริงจากหมู่บ้านใน registry</div>
            ) : (
              <div className={styles.villageGrid}>
                {villageStats.map((stat, index) => {
                  const judged = stat.correct + stat.incorrect;
                  const rate = judged ? stat.correct / judged : 0;
                  return (
                    <article key={stat.key} className={styles.villageCard}>
                      <div className={styles.cardHead}><span>{String(index + 1).padStart(2, "0")}</span><code>{stat.key}</code></div>
                      <h3>{stat.name}</h3>
                      <div className={styles.signalRow}><strong>{judged ? `${(rate * 100).toFixed(0)}%` : "—"}</strong><span>confirmed correct</span></div>
                      <div className={styles.bar}><i style={{ width: `${Math.max(rate * 100, judged ? 3 : 0)}%` }} /></div>
                      <footer><span>✓ {stat.correct}</span><span>× {stat.incorrect}</span><span>? {stat.unsure}</span><span>Σ {stat.total}</span></footer>
                    </article>
                  );
                })}
              </div>
            )}
          </section>

          <section className={styles.section}>
            <div className={styles.sectionLabel}><span>003</span><strong>NEEDS REVIEW</strong><span className={styles.sectionNote}>INCORRECT + UNSURE</span></div>
            {reviewItems.length === 0 ? <div className={styles.empty}>ไม่มีเคสที่ต้อง review ในข้อมูลที่โหลด</div> : (
              <div className={styles.reviewList}>
                {reviewItems.map((item) => (
                  <article key={item.receipt_id}>
                    <div className={`${styles.verdictFlag} ${styles[`v_${item.verdict.toLowerCase()}`]}`}>{verdictLabel[item.verdict]}</div>
                    <div><strong>{names.get(item.village_key) ?? (item.village_key || "ไม่ระบุหมู่บ้าน")}</strong><small>{fmtTime(item.recorded_at)} / {item.resolver_status}</small></div>
                    <div className={styles.routeData}><span>ระบบ <b>{item.selected_feeder || "—"}</b></span><span>Tester <b>{item.correction_feeder || "—"}</b></span></div>
                    <code>{item.correction_transformer || item.transformer_candidates[0] || "NO-TX"}</code>
                  </article>
                ))}
              </div>
            )}
          </section>

          <section className={styles.section}>
            <div className={styles.sectionLabel}><span>004</span><strong>RECENT FEEDBACK</strong></div>
            <div className={styles.tableWrap}>
              <table>
                <thead><tr><th>TIME</th><th>VILLAGE</th><th>VERDICT</th><th>SYSTEM</th><th>CORRECTION</th><th>RECEIPT</th></tr></thead>
                <tbody>
                  {data.items.filter((item) => !item.village_key.startsWith("SMOKE-")).slice(0, 40).map((item) => (
                    <tr key={item.receipt_id}>
                      <td>{fmtTime(item.recorded_at)}</td>
                      <td><strong>{names.get(item.village_key) ?? (item.village_key || "—")}</strong></td>
                      <td><span className={`${styles.tableVerdict} ${styles[`v_${item.verdict.toLowerCase()}`]}`}>{verdictLabel[item.verdict]}</span></td>
                      <td><code>{item.selected_feeder || "—"}</code><small>{item.transformer_candidates.join(", ") || "NO TX"}</small></td>
                      <td><code>{item.correction_feeder || "—"}</code><small>{item.correction_transformer || "—"}</small></td>
                      <td><code>{item.receipt_id}</code></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}

      <footer className={styles.footer}>
        <strong>PEA INTELLISENSE / BUENG KAN SHADOW PILOT</strong>
        <span>Structured feedback only · no raw customer text · production send blocked</span>
      </footer>
    </main>
  );
}
