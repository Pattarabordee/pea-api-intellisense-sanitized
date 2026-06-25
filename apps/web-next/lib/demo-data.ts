export type OperatorItem = {
  request_id: string;
  received_at: string;
  detected_at: string;
  status: string;
  callback_status: string;
  production_send: "blocked";
  etr_status?: string;
  send_control?: {
    policy_mode?: string;
    effective_mode?: string;
    eligibility_status?: string;
    decision?: string;
    reason?: string;
    gate_version?: string;
    production_send?: "blocked";
  };
  callback_outbox?: {
    status?: string;
    transport?: string;
    attempts?: number;
  };
  meter?: { hash?: string; last4?: string };
  result?: {
    evidence?: {
      reason?: string;
      source?: string;
      match_found?: boolean;
      match_level?: string;
      device_type?: string;
      device_id?: string;
      feeder?: string;
      event_time?: string;
      time_delta_minutes?: number;
    };
    pea_distribution?: {
      status?: string;
      reason?: string;
      cause_lane?: string;
    };
    etr?: {
      status?: string;
      etr_minutes_p50?: number;
      q10?: number;
      q90?: number;
      risk_level?: string;
      model_version?: string;
      production_gate?: string;
    };
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
    outbox_dry_run_held?: number;
    dead_letters?: number;
    latest_received_at?: string;
  };
  mvp?: {
    green_gate?: {
      green_rows?: number;
      min_green_rows?: number;
      additional_green_rows_needed?: number;
    };
    owner_queues?: {
      ais_truth_owner_rows?: number;
      pea_topology_owner_rows?: number;
    };
    ops_controls?: {
      backup_restore_drill?: string;
      render_alerts?: string;
      key_rotation_drill?: string;
      missing_tools?: string[];
      missing_env?: string[];
    };
    readiness?: {
      cloud_endpoint_ready?: string;
      production_infra_ready?: string;
      auto_etr_ready?: string;
    };
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
    pending_worker_traces: 2,
    not_ready_etr: 2,
    outbox_dry_run_held: 3,
    dead_letters: 0,
    latest_received_at: "2026-06-21T09:05:12Z"
  },
  mvp: {
    green_gate: {
      green_rows: 0,
      min_green_rows: 30,
      additional_green_rows_needed: 30
    },
    owner_queues: {
      ais_truth_owner_rows: 30,
      pea_topology_owner_rows: 30
    },
    ops_controls: {
      backup_restore_drill: "BLOCKED_MISSING_POSTGRES_TOOLS_OR_URLS",
      render_alerts: "MANUAL_CONFIRM_REQUIRED_OR_RENDER_API_KEY_MISSING",
      key_rotation_drill: "DEFER_UNTIL_FIRST_REAL_AIS_HIT",
      missing_tools: ["pg_dump", "pg_restore", "psql"],
      missing_env: ["DATABASE_URL", "RESTORE_TEST_DATABASE_URL", "RENDER_API_KEY"]
    },
    readiness: {
      cloud_endpoint_ready: "READY_FOR_DEPLOYMENT_PACKAGE",
      production_infra_ready: "BLOCKED_PENDING_OWNER_OR_CONTROL",
      auto_etr_ready: "BLOCKED_GREEN_GATE"
    }
  },
  items: [
    {
      request_id: "AIS-DEMO-VIDEO-0001",
      received_at: "2026-06-21T09:05:12Z",
      detected_at: "2026-06-21T16:04:00+07:00",
      status: "COMPLETED",
      callback_status: "CAPTURED_NO_CALLBACK_URL",
      production_send: "blocked",
      etr_status: "SHADOW_ONLY",
      send_control: {
        policy_mode: "blocked",
        effective_mode: "blocked",
        eligibility_status: "green_auto_candidate",
        decision: "blocked",
        reason: "green_gate_not_passed",
        gate_version: "blocked_green_gate",
        production_send: "blocked"
      },
      callback_outbox: { status: "DRY_RUN_HELD", transport: "dry_run", attempts: 0 },
      meter: { hash: "6ca13d52ca70c883", last4: "7890" },
      result: {
        evidence: {
          reason: "synthetic_demo_meter_to_protection_match",
          source: "Demo topology + protection event",
          match_found: true,
          match_level: "protection_device",
          device_type: "CB",
          device_id: "DEMO-CB-01",
          feeder: "DEMO-FDR-03",
          event_time: "2026-06-21T16:00:00+07:00",
          time_delta_minutes: 4
        },
        pea_distribution: {
          status: "SHADOW_CONFIRMED_PEA_CONTEXT",
          reason: "demo_meter_to_protection_and_event_time_match",
          cause_lane: "pea_no_backup"
        },
        etr: {
          status: "SHADOW_ONLY",
          etr_minutes_p50: 45,
          q10: 20,
          q90: 95,
          risk_level: "LOW",
          model_version: "shadow-demo",
          production_gate: "blocked_until_green_subset_passes"
        }
      }
    },
    {
      request_id: "AIS-DEMO-0002",
      received_at: "2026-06-21T08:47:34Z",
      detected_at: "2026-06-21T15:45:00+07:00",
      status: "COMPLETED",
      callback_status: "SKIPPED_DUPLICATE",
      production_send: "blocked",
      etr_status: "NOT_READY_FOR_AUTO_SEND",
      send_control: {
        policy_mode: "blocked",
        effective_mode: "blocked",
        eligibility_status: "red_blocked",
        decision: "blocked",
        reason: "duplicate_request_id",
        gate_version: "blocked_green_gate",
        production_send: "blocked"
      },
      callback_outbox: { status: "DRY_RUN_HELD", transport: "dry_run", attempts: 0 },
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
      send_control: {
        policy_mode: "blocked",
        effective_mode: "blocked",
        eligibility_status: "red_blocked",
        decision: "blocked",
        reason: "worker_pending",
        gate_version: "blocked_green_gate",
        production_send: "blocked"
      },
      callback_outbox: { status: "DRY_RUN_HELD", transport: "dry_run", attempts: 0 },
      meter: { hash: "95d4ab02f8ca7711", last4: "0455" },
      result: { evidence: { reason: "cloud_shadow_no_worker_result" } }
    }
  ]
};
