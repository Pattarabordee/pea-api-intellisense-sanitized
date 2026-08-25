"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import styles from "./tester.module.css";

type Catalog = {
  schemaVersion: number;
  supported: Array<{ key: string; name: string }>;
  excluded: Array<{ key: string; name: string }>;
};

type TopologyPrior = {
  feeder: string;
  core_meter_count: number;
  topology_share: number;
};

type ResolveResult = {
  status: string;
  mode: "shadow";
  production_send: "blocked";
  villageKey?: string;
  villageName?: string;
  supported: boolean;
  message: string;
  selectedFeeder?: string | null;
  selectedTransformerCandidates: string[];
  villageTransformerCandidates: string[];
  villageTransformerGroups: Array<{ feeder: string; transformers: string[] }>;
  footprintConfidence?: "HIGH" | "MEDIUM" | "LOW";
  topologyPrior: TopologyPrior[];
  protectionZone?: {
    gate?: string;
    devices: string[];
    coverage?: number | null;
    downstreamMeterCount?: number | null;
  } | null;
  matchedClues: string[];
  excludedReason?: string;
  coreCoverage?: number | null;
  outageLevel: "UNDETERMINED";
  requiredConfirmation: string[];
};

type Verdict = "CORRECT" | "INCORRECT" | "UNSURE";

const statusCopy: Record<string, { label: string; tone: "ok" | "warn" | "stop" | "info" }> = {
  RESOLVED_FOOTPRINT: { label: "พบตำแหน่ง Candidate", tone: "ok" },
  VILLAGE_ONLY_SINGLE_FEEDER: { label: "พบ Feeder / มีหลาย Candidate", tone: "info" },
  VILLAGE_ONLY_MULTI_FEEDER: { label: "ต้องระบุจุดสังเกตเพิ่ม", tone: "warn" },
  AMBIGUOUS_FOOTPRINT: { label: "ข้อมูลยังไม่พอ", tone: "warn" },
  AMBIGUOUS_VILLAGE: { label: "ชื่อหมู่บ้านกำกวม", tone: "warn" },
  UNSUPPORTED_VILLAGE: { label: "ยังไม่รองรับ", tone: "stop" },
  OUTSIDE_PILOT_SCOPE: { label: "นอกชุดทดสอบ", tone: "stop" }
};

const confidenceCopy = {
  HIGH: "สูง",
  MEDIUM: "ปานกลาง",
  LOW: "ต่ำ"
} as const;

function percent(value?: number | null) {
  if (value == null || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(value >= 0.995 ? 0 : 1)}%`;
}

function zoneLabel(gate?: string) {
  switch (gate) {
    case "STRONG_LOCAL_ZONE_CANDIDATE":
    case "STRONG_PAIR_ZONE_CANDIDATE":
    case "STRONG_BOUNDED_ZONE_CANDIDATE":
      return "ขอบเขต Protection ค่อนข้างเฉพาะ";
    case "BROAD_UPSTREAM_ZONE_CANDIDATE":
      return "Protection ต้นทางกว้าง";
    case "WEAK_PARTIAL_ZONE_CANDIDATE":
    case "PARTIAL_LOCAL_ZONE_CANDIDATE":
    case "PARTIAL_LOCAL_PLUS_BROAD_FULL_ZONE":
      return "Protection ครอบคลุมบางส่วน";
    case "INCONCLUSIVE_LOCAL_PROTECTION":
      return "ยังสรุป Protection ไม่ได้";
    default:
      return gate ? gate.replaceAll("_", " ") : "ยังไม่มีขอบเขต Protection";
  }
}

export function BuengKanTester({ catalog }: { catalog: Catalog }) {
  const [accessCode, setAccessCode] = useState("");
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<ResolveResult | null>(null);
  const [resolvedQuery, setResolvedQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [correctFeeder, setCorrectFeeder] = useState("");
  const [correctTransformer, setCorrectTransformer] = useState("");
  const [feedbackBusy, setFeedbackBusy] = useState(false);
  const [feedbackReceipt, setFeedbackReceipt] = useState("");
  const [copyState, setCopyState] = useState("");

  useEffect(() => {
    const saved = window.sessionStorage.getItem("bkTesterAccessCode");
    if (saved) setAccessCode(saved);
  }, []);

  const status = result ? statusCopy[result.status] ?? { label: result.status, tone: "info" as const } : null;
  const canFeedback = Boolean(result && query.trim());

  const resultText = useMemo(() => {
    if (!result) return "";
    const tx = result.selectedTransformerCandidates.length
      ? result.selectedTransformerCandidates.join(", ")
      : "ยังไม่ได้ narrow จากข้อความ";
    const villageTx = result.villageTransformerCandidates.length
      ? result.villageTransformerCandidates.join(", ")
      : "ยังไม่มี trace-confirmed core TX";
    const devices = result.protectionZone?.devices?.length
      ? result.protectionZone.devices.join(", ")
      : "ยังระบุไม่ได้";
    return [
      "PEA Intellisense · Bueng Kan GIS Tester (SHADOW)",
      `หมู่บ้าน: ${result.villageName ?? "—"}`,
      `สถานะ: ${status?.label ?? result.status}`,
      `Feeder: ${result.selectedFeeder ?? "ยังระบุไม่ได้"}`,
      `หม้อแปลงที่ narrow จากข้อความ: ${tx}`,
      `หม้อแปลงใน Core หมู่บ้าน (TraceDown): ${villageTx}`,
      `Protection: ${devices}`,
      `Confidence: ${result.footprintConfidence ? confidenceCopy[result.footprintConfidence] : "—"}`,
      "หมายเหตุ: เป็น GIS topology candidate ไม่ใช่การยืนยันว่าไฟดับจริง ต้องเทียบ ReportPO/ETR/OMS/SCADA/หน้างาน"
    ].join("\n");
  }, [result, status]);

  async function resolve(event?: FormEvent) {
    event?.preventDefault();
    const text = query.trim();
    if (!accessCode.trim()) {
      setError("กรุณาใส่ Tester Access Code");
      return;
    }
    if (!text) {
      setError("กรุณาระบุชื่อหมู่บ้านหรือข้อความแจ้งไฟดับ");
      return;
    }
    setLoading(true);
    setError("");
    setFeedbackReceipt("");
    setVerdict(null);
    try {
      const response = await fetch("/api/buengkan/resolve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        body: JSON.stringify({ accessCode: accessCode.trim(), text })
      });
      if (response.status === 401) {
        setError("Tester Access Code ไม่ถูกต้อง");
        setResult(null);
        return;
      }
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "RESOLVE_FAILED");
      setResult(data as ResolveResult);
      setResolvedQuery(text);
      window.sessionStorage.setItem("bkTesterAccessCode", accessCode.trim());
      window.setTimeout(() => document.getElementById("bk-result")?.scrollIntoView({ behavior: "smooth", block: "start" }), 20);
    } catch {
      setError("ระบบไม่สามารถประมวลผลได้ในขณะนี้ กรุณาลองใหม่");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  function chooseVillage(name: string) {
    setQuery(`บ้าน${name}ไฟดับ`);
    setResult(null);
    setResolvedQuery("");
    setError("");
    setFeedbackReceipt("");
    setVerdict(null);
  }

  async function copyResult() {
    if (!resultText) return;
    try {
      await navigator.clipboard.writeText(resultText);
      setCopyState("คัดลอกแล้ว");
    } catch {
      setCopyState("คัดลอกไม่สำเร็จ");
    }
    window.setTimeout(() => setCopyState(""), 1800);
  }

  async function submitFeedback() {
    if (!result || !verdict) return;
    setFeedbackBusy(true);
    setFeedbackReceipt("");
    try {
      const response = await fetch("/api/buengkan/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          accessCode: accessCode.trim(),
          query: resolvedQuery,
          verdict,
          villageKey: result.villageKey,
          status: result.status,
          selectedFeeder: result.selectedFeeder,
          transformerCandidates: result.selectedTransformerCandidates,
          correctFeeder,
          correctTransformer
        })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "FEEDBACK_FAILED");
      setFeedbackReceipt(data.receiptId);
    } catch {
      setFeedbackReceipt("ERROR");
    } finally {
      setFeedbackBusy(false);
    }
  }

  return (
    <main className={styles.shell} lang="th">
      <header className={styles.topbar}>
        <a className={styles.brandLink} href="/buengkan-tester">
          <span className={styles.brandMark}>PEA</span>
          <span className={styles.brandText}><strong>INTELLISENSE</strong><small>BUENG KAN / GIS TESTER</small></span>
        </a>
        <nav className={styles.nav} aria-label="Bueng Kan tester navigation">
          <span className={styles.navActive}>TESTER</span>
          <a href="/buengkan-tester/dashboard">FEEDBACK</a>
        </nav>
        <span className={styles.shadowBadge}><i /> SHADOW / LIVE</span>
      </header>

      <section className={styles.hero}>
        <div className={styles.heroCopy}>
          <p className={styles.eyebrow}>FIELD TEST / 001 · BUENG KAN GIS</p>
          <h1>Outage report,<br />meet GIS topology.</h1>
          <p className={styles.lead}>พิมพ์ชื่อหมู่บ้านหรือจุดสังเกต แล้วระบบจะคืน <strong>Feeder → หม้อแปลง Candidate → Protection Zone</strong> จาก topology ที่ผ่าน QA</p>
        </div>
        <aside className={styles.heroPanel}>
          <span>REGISTRY / V{catalog.schemaVersion}</span>
          <strong>{catalog.supported.length.toString().padStart(2, "0")}</strong>
          <p>SUPPORTED VILLAGES</p>
          <div />
          <small>GIS TOPOLOGY / STATIC EVIDENCE</small>
          <small>OUTAGE TRUTH / UNDETERMINED</small>
          <small>PRODUCTION SEND / BLOCKED</small>
        </aside>
        <div className={styles.safetyBanner} role="note">
          <span className={styles.safetyIcon}>!</span>
          <div>
            <strong>ผลนี้ไม่ใช่สถานะไฟดับจริง</strong>
            <p>ใช้เพื่อ Shadow Test เท่านั้น ต้องยืนยันกับ ReportPO / ETR / OMS / SCADA หรือหน้างานก่อนใช้งานเชิงปฏิบัติการ</p>
          </div>
        </div>
      </section>

      <section className={styles.card} aria-labelledby="search-heading">
        <div className={styles.sectionHead}>
          <div>
            <p className={styles.step}>001 / INPUT</p>
            <h2 id="search-heading">ใส่ข้อความที่ได้รับแจ้ง</h2>
          </div>
          <span className={styles.version}>Registry v{catalog.schemaVersion}</span>
        </div>

        <form onSubmit={resolve} className={styles.form}>
          <label className={styles.label} htmlFor="tester-code">Tester Access Code</label>
          <input
            id="tester-code"
            className={styles.input}
            type="password"
            autoComplete="off"
            autoCapitalize="characters"
            placeholder="วาง Tester Access Code ที่ได้รับ"
            value={accessCode}
            maxLength={64}
            onChange={(event) => setAccessCode(event.target.value)}
          />

          <label className={styles.label} htmlFor="outage-text">ข้อความแจ้งไฟดับ</label>
          <textarea
            id="outage-text"
            className={styles.textarea}
            rows={3}
            maxLength={500}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              if (result) {
                setResult(null);
                setResolvedQuery("");
                setFeedbackReceipt("");
                setVerdict(null);
              }
            }}
            placeholder="เช่น บ้านแสนประเสริฐ ซอยเทคนิค ไฟดับ"
          />

          <button className={styles.primaryButton} type="submit" disabled={loading}>
            {loading ? <span className={styles.spinner} aria-hidden="true" /> : <span aria-hidden="true">⌕</span>}
            {loading ? "กำลังตรวจ GIS topology…" : "ตรวจสอบหม้อแปลง Candidate"}
          </button>
          {error && <p className={styles.error} role="alert">{error}</p>}
        </form>

        <div className={styles.quickArea}>
          <span className={styles.mutedLabel}>แตะเพื่อทดลองชื่อหมู่บ้าน</span>
          <div className={styles.chips}>
            {catalog.supported.map((item) => (
              <button key={item.key} className={styles.chip} type="button" onClick={() => chooseVillage(item.name)}>
                {item.name}
              </button>
            ))}
          </div>
        </div>

        <details className={styles.details}>
          <summary>หมู่บ้านที่ยังไม่เปิดให้ระบบคาดเดา ({catalog.excluded.length})</summary>
          <p>{catalog.excluded.map((item) => item.name).filter(Boolean).join(" · ")}</p>
        </details>
      </section>

      {result && (
        <section id="bk-result" className={`${styles.card} ${styles.resultCard}`} aria-live="polite">
          <div className={styles.sectionHead}>
            <div>
              <p className={styles.step}>002 / TOPOLOGY</p>
              <h2>ผลจาก GIS Topology</h2>
            </div>
            <span className={`${styles.statusPill} ${styles[`tone_${status?.tone ?? "info"}`]}`}>{status?.label}</span>
          </div>

          <div className={styles.villageTitle}>
            <span>หมู่บ้าน</span>
            <strong>{result.villageName ?? "ยังไม่พบในชุดทดสอบ"}</strong>
          </div>

          <div className={styles.flow} aria-label="Topology result">
            <div className={styles.flowNode}>
              <span>Feeder</span>
              <strong>{result.selectedFeeder ?? (result.topologyPrior.length > 1 ? "หลาย Feeder" : "—")}</strong>
            </div>
            <div className={styles.flowArrow} aria-hidden="true">→</div>
            <div className={styles.flowNode}>
              <span>{result.status === "RESOLVED_FOOTPRINT" && result.selectedTransformerCandidates.length ? "หม้อแปลง Candidate จากข้อความ" : "หม้อแปลงใน Core หมู่บ้าน"}</span>
              <strong>{result.status === "RESOLVED_FOOTPRINT" && result.selectedTransformerCandidates.length
                ? `${result.selectedTransformerCandidates.length} ลูก`
                : result.villageTransformerCandidates.length
                  ? `${result.villageTransformerCandidates.length} ลูก`
                  : "ยังไม่มีข้อมูล"}</strong>
            </div>
            <div className={styles.flowArrow} aria-hidden="true">→</div>
            <div className={styles.flowNode}>
              <span>ความมั่นใจ GIS · ไม่ใช่สถานะดับ</span>
              <strong>{result.footprintConfidence ? confidenceCopy[result.footprintConfidence] : "—"}</strong>
            </div>
          </div>

          <p className={styles.resultMessage}>{result.message}</p>
          {result.footprintConfidence && <p className={styles.confidenceNote}>ความมั่นใจนี้หมายถึงความชัดเจนของการจับคู่ GIS topology ไม่ใช่ความน่าจะเป็นที่ไฟกำลังดับ</p>}

          {result.status === "RESOLVED_FOOTPRINT" && result.selectedTransformerCandidates.length > 0 && (
            <div className={styles.resultBlock}>
              <div className={styles.blockHead}>
                <h3>หม้อแปลง Candidate ที่ narrow ได้จากข้อความ</h3>
                <span className={styles.smallBadge}>{result.selectedTransformerCandidates.length} ลูก</span>
              </div>
              <div className={styles.txList}>
                {result.selectedTransformerCandidates.map((tx, index) => (
                  <div className={styles.txItem} key={tx}>
                    <span className={styles.txIndex}>{index + 1}</span>
                    <code>{tx}</code>
                  </div>
                ))}
              </div>
            </div>
          )}

          {result.villageTransformerGroups.length > 0 && (
            <div className={styles.resultBlock}>
              <div className={styles.blockHead}>
                <h3>หม้อแปลงที่ TraceDown พบใน Core หมู่บ้าน</h3>
                <span className={styles.smallBadge}>{result.villageTransformerCandidates.length} ลูก</span>
              </div>
              <p className={styles.confidenceNote}>แสดงเลขหม้อแปลง/Facility ID ที่มี core overlap &gt; 0 เท่านั้น เป็น static GIS topology candidate ไม่ใช่การยืนยันว่าหม้อแปลงกำลังดับ</p>
              <div className={styles.txGroups}>
                {result.villageTransformerGroups.map((group) => (
                  <section className={styles.txGroup} key={group.feeder}>
                    <div className={styles.txGroupHead}>
                      <strong>{group.feeder}</strong>
                      <span>{group.transformers.length} ลูก</span>
                    </div>
                    <div className={styles.txList}>
                      {group.transformers.map((tx, index) => (
                        <div className={styles.txItem} key={`${group.feeder}-${tx}`}>
                          <span className={styles.txIndex}>{index + 1}</span>
                          <code>{tx}</code>
                        </div>
                      ))}
                    </div>
                  </section>
                ))}
              </div>
            </div>
          )}

          {result.topologyPrior.length > 0 && (
            <div className={styles.resultBlock}>
              <h3>Feeder ที่พบใน Core ของหมู่บ้าน</h3>
              <div className={styles.priorList}>
                {result.topologyPrior.map((item) => (
                  <div className={styles.priorRow} key={item.feeder}>
                    <div className={styles.priorText}>
                      <strong>{item.feeder}</strong>
                      <span>{item.core_meter_count} จุด · {percent(item.topology_share)}</span>
                    </div>
                    <div className={styles.barTrack} aria-hidden="true">
                      <span className={styles.barFill} style={{ width: `${Math.max(item.topology_share * 100, 2)}%` }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {result.protectionZone && (
            <div className={styles.resultBlock}>
              <div className={styles.blockHead}>
                <h3>Protection Zone Candidate</h3>
                <span className={styles.smallBadge}>{zoneLabel(result.protectionZone.gate)}</span>
              </div>
              <dl className={styles.metricsGrid}>
                <div><dt>อุปกรณ์</dt><dd>{result.protectionZone.devices.length ? result.protectionZone.devices.join(", ") : "—"}</dd></div>
                <div><dt>Coverage</dt><dd>{percent(result.protectionZone.coverage)}</dd></div>
                <div><dt>Downstream meters</dt><dd>{result.protectionZone.downstreamMeterCount?.toLocaleString("th-TH") ?? "—"}</dd></div>
              </dl>
            </div>
          )}

          {result.status === "UNSUPPORTED_VILLAGE" && (
            <div className={styles.stopPanel}>
              <strong>Fail closed — ระบบจะไม่เดา</strong>
              <p>{result.excludedReason || "Topology coverage ยังไม่ถึง gate ที่กำหนด"}</p>
              {result.coreCoverage != null && <p>Coverage ล่าสุด: {percent(result.coreCoverage)}</p>}
            </div>
          )}

          <div className={styles.truthBox}>
            <strong>Outage level: UNDETERMINED</strong>
            <p>GIS บอกความสัมพันธ์ทางไฟฟ้า แต่ไม่ยืนยันว่าอุปกรณ์กำลังขัดข้อง ต้องมีหลักฐาน operational เพิ่ม</p>
            <ul>
              {result.requiredConfirmation.map((item) => <li key={item}>{item}</li>)}
            </ul>
          </div>

          <button className={styles.secondaryButton} type="button" onClick={copyResult}>
            คัดลอกผลเพื่อส่งต่อ {copyState && <span>· {copyState}</span>}
          </button>
        </section>
      )}

      {canFeedback && result && (
        <section className={styles.card}>
          <div className={styles.sectionHead}>
            <div>
              <p className={styles.step}>003 / FIELD TRUTH</p>
              <h2>Tester เห็นว่าผลนี้ถูกไหม?</h2>
            </div>
          </div>

          <div className={styles.verdictGrid} role="group" aria-label="ผลการตรวจของ Tester">
            <button className={`${styles.verdictButton} ${verdict === "CORRECT" ? styles.verdictActive : ""}`} onClick={() => setVerdict("CORRECT")} type="button" aria-pressed={verdict === "CORRECT"}>
              <span aria-hidden="true">✓</span><strong>ถูกต้อง</strong><small>ตรงกับหน้างาน/GIS ที่ Tester ทราบ</small>
            </button>
            <button className={`${styles.verdictButton} ${verdict === "INCORRECT" ? styles.verdictActive : ""}`} onClick={() => setVerdict("INCORRECT")} type="button" aria-pressed={verdict === "INCORRECT"}>
              <span aria-hidden="true">×</span><strong>ไม่ถูกต้อง</strong><small>Feeder / TX / Zone ไม่ตรง</small>
            </button>
            <button className={`${styles.verdictButton} ${verdict === "UNSURE" ? styles.verdictActive : ""}`} onClick={() => setVerdict("UNSURE")} type="button" aria-pressed={verdict === "UNSURE"}>
              <span aria-hidden="true">?</span><strong>ไม่แน่ใจ</strong><small>ต้องเปิด GIS หรือเช็กเพิ่ม</small>
            </button>
          </div>

          {(verdict === "INCORRECT" || verdict === "UNSURE") && (
            <div className={styles.correctionBox}>
              <p className={styles.privacyNote}><strong>ห้ามใส่</strong> ชื่อผู้ใช้ไฟ, เบอร์โทร, เลขผู้ใช้ไฟ, PEANO หรือข้อมูลส่วนบุคคล</p>
              <div className={styles.twoCols}>
                <label>Feeder ที่ถูกต้อง (ถ้าทราบ)
                  <input className={styles.input} maxLength={24} value={correctFeeder} onChange={(e) => setCorrectFeeder(e.target.value)} placeholder="เช่น BUA07" />
                </label>
                <label>หม้อแปลงที่ถูกต้อง (ถ้าทราบ)
                  <input className={styles.input} maxLength={32} value={correctTransformer} onChange={(e) => setCorrectTransformer(e.target.value)} placeholder="เช่น 60-037069" />
                </label>
              </div>
              <p className={styles.privacyNote}>ระบบบันทึกเฉพาะผลทดสอบและ Feeder/TX ที่แก้ไข ไม่บันทึกข้อความหมายเหตุอิสระหรือข้อมูลผู้ใช้ไฟ</p>
            </div>
          )}

          <button className={styles.primaryButton} type="button" disabled={!verdict || feedbackBusy || Boolean(feedbackReceipt && feedbackReceipt !== "ERROR")} onClick={submitFeedback}>
            {feedbackBusy ? "กำลังบันทึก…" : feedbackReceipt && feedbackReceipt !== "ERROR" ? "ส่งผลแล้ว" : "ส่งผลการทดสอบ"}
          </button>
          {feedbackReceipt && feedbackReceipt !== "ERROR" && (
            <div className={styles.receipt} role="status">
              <strong>บันทึกแล้ว</strong>
              <span>Receipt: {feedbackReceipt}</span>
            </div>
          )}
          {feedbackReceipt === "ERROR" && <p className={styles.error} role="alert">บันทึก feedback ไม่สำเร็จ กรุณาลองใหม่</p>}
        </section>
      )}

      <footer className={styles.footer}>
        <strong>PEA Intellisense · Bueng Kan Shadow Pilot</strong>
        <span>ไม่มี Production Send · ไม่มีข้อมูลลูกค้า/PEANO ในหน้านี้</span>
      </footer>
    </main>
  );
}
