export type OperatorItem = {
  request_id: string;
  received_at: string;
  detected_at: string;
  status: string;
  callback_status: string;
  production_send: "blocked";
  etr_status?: string;
  meter?: { hash?: string; last4?: string };
  result?: {
    evidence?: { reason?: string };
  };
};

export type OperatorData = {
  api_version: string;
  schema_version: string;
  mode: "shadow";
  production_send: "blocked";
  count: number;
  generated_at: string;
  source?: string;
  metrics?: {
    total_requests?: number;
    duplicate_callbacks?: number;
    pending_worker_traces?: number;
    not_ready_etr?: number;
    latest_received_at?: string;
  };
  items: OperatorItem[];
};

export const demoOperatorData: OperatorData = {
  api_version: "v1",
  schema_version: "2026-06-20",
  mode: "shadow",
  production_send: "blocked",
  count: 3,
  generated_at: "2026-06-21T00:00:00Z",
  source: "demo redacted fallback",
  metrics: {
    total_requests: 3,
    duplicate_callbacks: 1,
    pending_worker_traces: 3,
    not_ready_etr: 3,
    latest_received_at: "2026-06-21T09:05:12Z"
  },
  items: [
    {
      request_id: "AIS-DEMO-0003",
      received_at: "2026-06-21T09:05:12Z",
      detected_at: "2026-06-21T16:04:00+07:00",
      status: "COMPLETED",
      callback_status: "CAPTURED_NO_CALLBACK_URL",
      production_send: "blocked",
      etr_status: "NOT_READY_FOR_AUTO_SEND",
      meter: { hash: "6ca13d52ca70c883", last4: "7890" },
      result: { evidence: { reason: "python_worker_pending_or_no_evidence_loaded" } }
    },
    {
      request_id: "AIS-DEMO-0002",
      received_at: "2026-06-21T08:47:34Z",
      detected_at: "2026-06-21T15:45:00+07:00",
      status: "COMPLETED",
      callback_status: "SKIPPED_DUPLICATE",
      production_send: "blocked",
      etr_status: "NOT_READY_FOR_AUTO_SEND",
      meter: { hash: "a1b2c3d4e5f60718", last4: "4312" },
      result: { evidence: { reason: "request_id_already_received" } }
    },
    {
      request_id: "AIS-DEMO-0001",
      received_at: "2026-06-21T08:30:11Z",
      detected_at: "2026-06-21T15:29:00+07:00",
      status: "COMPLETED",
      callback_status: "CAPTURED_NO_CALLBACK_URL",
      production_send: "blocked",
      etr_status: "NOT_READY_FOR_AUTO_SEND",
      meter: { hash: "95d4ab02f8ca7711", last4: "0455" },
      result: { evidence: { reason: "cloud_shadow_no_worker_result" } }
    }
  ]
};
