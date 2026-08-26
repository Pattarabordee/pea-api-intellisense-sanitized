"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import styles from "./validation.module.css";

type Candidate = {
  facility_id: string;
  feeder_id: string;
  location: { lat?: number | null; lon?: number | null; crs: string; source: string };
  approx_source_to_lv_distance_m?: number | null;
};

type CatalogItem = {
  source_type: "POI" | "ROAD_SOI";
  source_ref: string;
  label: string;
  category: string;
  priority: string;
  validation_status: string;
  resolver_status: string;
  known_conflict: boolean;
  prior_evidence: { check: string; transformers: string[]; rules: string[] };
  source_location: { lat?: number | null; lon?: number | null; crs: string; source: string };
  candidates: Candidate[];
  candidate_count: number;
  provenance: string;
  candidate_scope: "POI_POINT_FIELD_VALIDATION_ONLY" | "ROAD_REPRESENTATIVE_POINT_FIELD_VALIDATION_ONLY";
  outage_state: "UNDETERMINED";
};

type Catalog = {
  schema_version: string;
  registry_version: number;
  item_count: number;
  source_counts: Record<string, number>;
  priority_counts: Record<string, number>;
  promotion_policy: string;
  items: CatalogItem[];
};

type ValidationRecord = {
  receipt_id: string;
  recorded_at: string;
  source_type: string;
  source_ref: string;
  source_label: string;
  validator_ref?: string;
  priority: string;
  verdict: "CORRECT" | "INCORRECT" | "UNSURE";
  candidate_transformers: string[];
  selected_transformer: string;
  correction_transformer: string;
  correction_feeder: string;
  validation_scope?: string;
};

type ValidationData = {
  catalog: Catalog;
  validations: ValidationRecord[];
  summary: { total: number; correct: number; incorrect: number; unsure: number; latest_at?: string };
  mode: "shadow";
  production_send: "blocked";
  auto_promotion: false;
};

const priorityLabels: Record<string, string> = {
  P0_CONFLICT: "P0 · CONFLICT",
  P1_HIGH_VALUE_SINGLE: "P1 · HIGH VALUE",
  P1_LOCAL_SINGLE_TX: "P1 · LOCAL ROAD",
  P2_SINGLE_REVIEW: "P2 · SINGLE REVIEW",
  P2_ROAD_SINGLE_TX: "P2 · ROAD SINGLE",
  P3_AMBIGUOUS: "P3 · AMBIGUOUS",
  P3_MULTI_TX_CORRIDOR: "P3 · MULTI-TX",
  P4_NO_COVERAGE: "P4 · NO COVERAGE"
};

function mapURL(lat?: number | null, lon?: number | null) {
  if (typeof lat !== "number" || typeof lon !== "number") return "";
  return `https://www.google.com/maps/search/?api=1&query=${lat},${lon}`;
}

function latestBySource(rows: ValidationRecord[]) {
  const result = new Map<string, ValidationRecord>();
  for (const row of rows) if (!result.has(row.source_ref)) result.set(row.source_ref, row);
  return result;
}

function getValidatorRef() {
  const key = "bkFieldValidatorRef";
  const existing = window.localStorage.getItem(key);
  if (existing) return existing;
  const raw = crypto.randomUUID().replaceAll("-", "");
  const value = `validator_${raw}`;
  window.localStorage.setItem(key, value);
  return value;
}

function VerdictBadge({ verdict }: { verdict?: ValidationRecord["verdict"] }) {
  if (!verdict) return <span className={styles.pendingBadge}>PENDING</span>;
  const label = verdict === "CORRECT" ? "CONFIRMED" : verdict === "INCORRECT" ? "REJECTED" : "UNSURE";
  return <span className={`${styles.verdictBadge} ${styles[`verdict_${verdict.toLowerCase()}`]}`}>{label}</span>;
}

function ValidationCard({ item, latest, accessCode, validatorRef, onStored }: {
  item: CatalogItem;
  latest?: ValidationRecord;
  accessCode: string;
  validatorRef: string;
  onStored: () => Promise<void>;
}) {
  const [selected, setSelected] = useState(item.candidates.length === 1 ? item.candidates[0].facility_id : "");
  const [correctionTx, setCorrectionTx] = useState("");
  const [correctionFeeder, setCorrectionFeeder] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function submit(verdict: "CORRECT" | "INCORRECT" | "UNSURE") {
    if (verdict === "CORRECT" && item.candidates.length > 1 && !selected) {
      setMessage("เลือกหม้อแปลงที่ยืนยันจากหน้างานก่อน");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch("/api/buengkan/validation/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        body: JSON.stringify({
          accessCode,
          validatorRef,
          sourceType: item.source_type,
          sourceRef: item.source_ref,
          verdict,
          selectedTransformer: selected,
          correctionTransformer: correctionTx,
          correctionFeeder
        })
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || data.error || "บันทึกไม่สำเร็จ");
      setMessage(`บันทึกแล้ว · ${data.receiptId}`);
      await onStored();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "บันทึกไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  const sourceMap = mapURL(item.source_location.lat, item.source_location.lon);
  return (
    <article data-validation-card={item.source_ref} className={`${styles.itemCard} ${item.known_conflict ? styles.conflictCard : ""}`}>
      <div className={styles.itemTop}>
        <div>
          <span className={styles.priority}>{priorityLabels[item.priority] ?? item.priority}</span>
          <h3>{item.label}</h3>
          <p>{item.category} · {item.source_type === "POI" ? "PEA POI" : "Road/Soi secondary"}</p>
        </div>
        <VerdictBadge verdict={latest?.verdict} />
      </div>

      {item.known_conflict && (
        <div className={styles.conflictBanner}>
          <strong>CONFLICT REVIEW</strong>
          <span>POI proximity กับ prior TraceDown landmark ชี้คนละ TX — ห้าม promote อัตโนมัติ</span>
        </div>
      )}

      <div className={styles.sourceStrip}>
        <span>REF <code>{item.source_ref}</code></span>
        <span>PROVENANCE <b>{item.provenance}</b></span>
        {sourceMap ? <a href={sourceMap} target="_blank" rel="noreferrer">เปิดตำแหน่ง ↗</a> : <span>NO MAP POINT</span>}
      </div>

      <div className={styles.truthWarning}>
        {item.source_type === "ROAD_SOI"
          ? "ยืนยันเฉพาะความสัมพันธ์ ณ จุดตัวแทนที่เปิดบนแผนที่ ไม่ใช่ยืนยันว่าถนน/ซอยทั้งเส้นอยู่ TX เดียว และไม่ใช่หลักฐานว่า TX กำลังดับ"
          : "ตำแหน่งใกล้สาย LV ≠ ยืนยันว่าอาคารรับไฟจาก TX นี้ ต้องตรวจจากหน้างานหรือหลักฐาน topology เพิ่มเติม และไม่ใช่หลักฐานว่า TX กำลังดับ"}
      </div>

      <div className={styles.candidates}>
        {item.candidates.length === 0 ? (
          <div className={styles.noCandidate}>ยังไม่มี LV-service candidate ใน radius ที่กำหนด — ใช้สำหรับตรวจ coverage เท่านั้น</div>
        ) : item.candidates.map((candidate, index) => {
          const txMap = mapURL(candidate.location.lat, candidate.location.lon);
          const checked = selected === candidate.facility_id;
          return (
            <div key={candidate.facility_id} data-candidate-card={candidate.facility_id} className={`${styles.candidateCard} ${checked ? styles.candidateSelected : ""}`}>
              <label className={styles.candidateChoice}>
                {item.candidates.length > 1 && (
                  <input type="radio" name={`tx-${item.source_ref}`} value={candidate.facility_id} checked={checked} onChange={() => setSelected(candidate.facility_id)} />
                )}
                <span className={styles.candidateIndex}>{String(index + 1).padStart(2, "0")}</span>
                <span className={styles.candidateBody}>
                  <strong>{candidate.facility_id}</strong>
                  <span>Feeder {candidate.feeder_id || "—"}</span>
                  <span>TX: {candidate.location.lat?.toFixed(6) ?? "—"}, {candidate.location.lon?.toFixed(6) ?? "—"}</span>
                  <span>source→LV ≈ {candidate.approx_source_to_lv_distance_m == null ? "—" : `${candidate.approx_source_to_lv_distance_m.toFixed(1)} m`}</span>
                </span>
              </label>
              {txMap && <a className={styles.txMap} href={txMap} target="_blank" rel="noreferrer">TX map ↗</a>}
            </div>
          );
        })}
      </div>

      <details className={styles.correction}>
        <summary>ถ้าระบบเสนอผิด และทราบค่าที่ถูกต้อง</summary>
        <div className={styles.correctionGrid}>
          <label>Feeder ที่ถูกต้อง
            <input maxLength={24} value={correctionFeeder} onChange={(e) => setCorrectionFeeder(e.target.value)} placeholder="เช่น BUA07" />
          </label>
          <label>Facility ID หม้อแปลงที่ถูกต้อง
            <input maxLength={32} value={correctionTx} onChange={(e) => setCorrectionTx(e.target.value)} placeholder="เช่น 60-037069" />
          </label>
        </div>
      </details>

      <div className={styles.actions}>
        <button type="button" className={styles.correct} disabled={busy || item.candidates.length === 0 || (item.candidates.length > 1 && !selected)} onClick={() => submit("CORRECT")}>{item.source_type === "ROAD_SOI" ? "✓ ถูก ณ จุดตรวจ" : "✓ ถูก / ยืนยัน TX"}</button>
        <button type="button" className={styles.incorrect} disabled={busy} onClick={() => submit("INCORRECT")}>× ไม่ถูก</button>
        <button type="button" className={styles.unsure} disabled={busy} onClick={() => submit("UNSURE")}>? ไม่แน่ใจ</button>
      </div>
      {message && <p className={styles.cardMessage} role="status">{message}</p>}
      {latest && <p className={styles.latest}>ล่าสุด: {latest.verdict} · {new Date(latest.recorded_at).toLocaleString("th-TH")}{latest.validator_ref === validatorRef ? " · เครื่องนี้" : ""}</p>}
    </article>
  );
}

export function BuengKanFieldValidation() {
  const [accessCode, setAccessCode] = useState("");
  const [validatorRef, setValidatorRef] = useState("");
  const [data, setData] = useState<ValidationData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [sourceFilter, setSourceFilter] = useState("ALL");
  const [priorityFilter, setPriorityFilter] = useState("ACTIVE");
  const [pendingOnly, setPendingOnly] = useState(true);
  const [search, setSearch] = useState("");

  useEffect(() => {
    setValidatorRef(getValidatorRef());
    const saved = window.sessionStorage.getItem("bkTesterAccessCode");
    if (saved) setAccessCode(saved);
  }, []);

  async function loadCatalog(code = accessCode) {
    const trimmed = code.trim();
    if (!trimmed) { setError("กรุณาใส่ Tester Access Code"); return; }
    setLoading(true);
    setError("");
    try {
      const response = await fetch("/api/buengkan/validation/catalog", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        body: JSON.stringify({ accessCode: trimmed })
      });
      if (response.status === 401) throw new Error("Tester Access Code ไม่ถูกต้อง");
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.catalog) throw new Error(payload.error || "โหลด validation catalog ไม่สำเร็จ");
      window.sessionStorage.setItem("bkTesterAccessCode", trimmed);
      setData(payload as ValidationData);
    } catch (err) {
      setData(null);
      setError(err instanceof Error ? err.message : "โหลดข้อมูลไม่สำเร็จ");
    } finally { setLoading(false); }
  }

  function unlock(event: FormEvent) {
    event.preventDefault();
    void loadCatalog();
  }

  const latest = useMemo(() => latestBySource(data?.validations ?? []), [data]);
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (data?.catalog.items ?? []).filter((item) => {
      if (sourceFilter !== "ALL" && item.source_type !== sourceFilter) return false;
      if (priorityFilter === "ACTIVE" && (item.priority.startsWith("P3") || item.priority.startsWith("P4"))) return false;
      if (priorityFilter !== "ALL" && priorityFilter !== "ACTIVE" && !item.priority.startsWith(priorityFilter)) return false;
      if (pendingOnly && latest.has(item.source_ref)) return false;
      if (q && !`${item.label} ${item.category} ${item.source_ref}`.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [data, sourceFilter, priorityFilter, pendingOnly, search, latest]);

  const adjudicated = (data?.summary.correct ?? 0) + (data?.summary.incorrect ?? 0);

  return (
    <main className={styles.shell}>
      <header className={styles.topbar}>
        <a className={styles.brand} href="/buengkan-tester"><span className={styles.brandMark}>PEA</span><span><strong>INTELLISENSE</strong><small>BUENG KAN / FIELD VALIDATION</small></span></a>
        <nav className={styles.nav} aria-label="Bueng Kan navigation">
          <a href="/buengkan-tester">TESTER</a>
          <span className={styles.navActive} aria-current="page">VALIDATE</span>
          <a href="/buengkan-tester/dashboard">FEEDBACK</a>
        </nav>
        <span className={styles.live}><i /> SHADOW / TEST</span>
      </header>

      <section className={styles.hero}>
        <div>
          <p className={styles.eyebrow}>FIELD EVIDENCE / 012</p>
          <h1>Validate before<br />we trust it.</h1>
          <p className={styles.lead}>ตรวจสถานที่สำคัญ ถนน และซอยเทียบกับระบบไฟจริงก่อนนำ evidence ไป narrow หม้อแปลงใน LINE/Facebook workflow</p>
        </div>
        <div className={styles.heroPanel}>
          <span>CATALOG</span><strong>{data?.catalog.item_count?.toString().padStart(2, "0") ?? "91"}</strong><p>FIELD CHECKS</p>
          <div /><small>NO AUTO PROMOTION</small><small>NO CUSTOMER PII</small><small>TX = PEA GIS FACILITYID</small>
        </div>
        <div className={styles.safetyBanner}><span>!</span><div><strong>Field validation ≠ outage confirmation</strong><p>การกด “ถูก” ยืนยันเฉพาะความสัมพันธ์ของสถานที่/ถนนกับ TX candidate ไม่ได้ยืนยันว่า TX กำลังดับ และยังไม่เปลี่ยน resolver อัตโนมัติ</p></div></div>
      </section>

      {!data ? (
        <section className={styles.unlockCard}>
          <p className={styles.sectionIndex}>001 / ACCESS</p><h2>เปิด Field Validation</h2>
          <form onSubmit={unlock} className={styles.unlockForm}>
            <label>Tester Access Code<input type="password" autoComplete="off" maxLength={64} value={accessCode} onChange={(e) => setAccessCode(e.target.value)} /></label>
            <button type="submit" disabled={loading}>{loading ? "กำลังโหลด…" : "เปิด Validation Queue"}</button>
          </form>
          {error && <p className={styles.error}>{error}</p>}
        </section>
      ) : (
        <>
          <section className={styles.stats}>
            <article><span>CATALOG</span><strong>{data.catalog.item_count}</strong><small>POI {data.catalog.source_counts.POI} · ROAD/SOI {data.catalog.source_counts.ROAD_SOI}</small></article>
            <article><span>VALIDATIONS</span><strong>{data.summary.total}</strong><small>durable Postgres records</small></article>
            <article className={styles.statGood}><span>CONFIRMED</span><strong>{data.summary.correct}</strong><small>{adjudicated ? `${Math.round(data.summary.correct / adjudicated * 100)}% adjudicated` : "no adjudicated cases"}</small></article>
            <article className={styles.statWarn}><span>NEEDS REVIEW</span><strong>{data.summary.incorrect + data.summary.unsure}</strong><small>incorrect + unsure</small></article>
          </section>

          <section className={styles.controls}>
            <div className={styles.controlHead}><div><p className={styles.sectionIndex}>002 / QUEUE</p><h2>รายการตรวจหน้างาน</h2></div><button onClick={() => void loadCatalog()} disabled={loading}>↻ Refresh</button></div>
            <div className={styles.filters}>
              <label>ค้นหา<input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="ชื่อสถานที่ / ถนน / source ref" /></label>
              <label>ประเภท<select value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)}><option value="ALL">ทั้งหมด</option><option value="POI">POI</option><option value="ROAD_SOI">ถนน / ซอย</option></select></label>
              <label>Priority<select value={priorityFilter} onChange={(e) => setPriorityFilter(e.target.value)}><option value="ACTIVE">P0–P2 ก่อน</option><option value="P0">P0 Conflict</option><option value="P1">P1</option><option value="P2">P2</option><option value="P3">P3 Ambiguous</option><option value="P4">P4 No coverage</option><option value="ALL">ทั้งหมด</option></select></label>
              <label className={styles.check}><input type="checkbox" checked={pendingOnly} onChange={(e) => setPendingOnly(e.target.checked)} /> แสดงเฉพาะที่ยังไม่ตรวจ</label>
            </div>
            <div className={styles.queueMeta}><span>SHOWING <b>{filtered.length}</b> / {data.catalog.item_count}</span><span>VALIDATOR <code>{validatorRef.slice(0, 18)}…</code></span><span>AUTO PROMOTION <b>OFF</b></span></div>
          </section>

          <section className={styles.grid}>
            {filtered.length === 0 ? <div className={styles.empty}>ไม่มีรายการตาม filter นี้</div> : filtered.map((item) => (
              <ValidationCard key={item.source_ref} item={item} latest={latest.get(item.source_ref)} accessCode={accessCode} validatorRef={validatorRef} onStored={() => loadCatalog()} />
            ))}
          </section>
        </>
      )}

      <footer className={styles.footer}><span>PEA INTELLISENSE / BUENG KAN</span><span>FIELD VALIDATION ONLY · SHADOW · PRODUCTION SEND BLOCKED</span></footer>
    </main>
  );
}
