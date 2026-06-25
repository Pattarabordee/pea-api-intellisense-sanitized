package sendcontrol

import "strings"

const (
	ModeBlocked             = "blocked"
	ModeHumanReviewOnly     = "human_review_only"
	ModeStatusOnlyGreenLane = "status_only_green_lane"
	ModeAutoGreenLane       = "auto_green_lane"
	ModeEmergencyOff        = "emergency_off"

	DecisionBlocked        = "blocked"
	DecisionHumanReview    = "human_review_required"
	DecisionStatusDryRun   = "status_only_dry_run"
	DecisionAutoGreenDryRun = "auto_green_dry_run"
	DecisionEmergencyOff   = "emergency_off"

	TransportDryRun = "dry_run"
	TransportReal   = "real"
)

type Policy struct {
	Mode              string
	EmergencyOff      bool
	CallbackTransport string
	GateVersion       string
	Source            string
}

type Candidate struct {
	EligibilityStatus string
	GatePassed        bool
	OwnerApproved     bool
	CallbackApproved  bool
}

type Decision struct {
	PolicyMode        string
	EffectiveMode     string
	EligibilityStatus string
	Decision          string
	Reason            string
	GateVersion       string
	Source            string
	Transport         string
}

func NormalizePolicy(policy Policy) Policy {
	policy.Mode = normalizeMode(policy.Mode)
	if policy.EmergencyOff {
		policy.Mode = ModeEmergencyOff
	}
	policy.CallbackTransport = normalizeTransport(policy.CallbackTransport)
	if policy.GateVersion == "" {
		policy.GateVersion = "blocked_green_gate"
	}
	if policy.Source == "" {
		policy.Source = "api"
	}
	return policy
}

func Evaluate(policy Policy, candidate Candidate) Decision {
	policy = NormalizePolicy(policy)
	eligibility := strings.TrimSpace(candidate.EligibilityStatus)
	if eligibility == "" {
		eligibility = "red_blocked"
	}
	decision := Decision{
		PolicyMode:        policy.Mode,
		EffectiveMode:     policy.Mode,
		EligibilityStatus: eligibility,
		Decision:          DecisionBlocked,
		Reason:            "production_send_blocked_by_default",
		GateVersion:       policy.GateVersion,
		Source:            policy.Source,
		Transport:         policy.CallbackTransport,
	}
	if policy.Mode == ModeEmergencyOff {
		decision.Decision = DecisionEmergencyOff
		decision.Reason = "emergency_off_override"
		return decision
	}
	if !candidate.GatePassed {
		decision.Reason = "green_gate_not_passed"
		return decision
	}
	if !candidate.OwnerApproved {
		decision.Reason = "owner_approval_missing"
		return decision
	}
	if !candidate.CallbackApproved {
		decision.Reason = "callback_contract_not_approved"
		return decision
	}
	switch policy.Mode {
	case ModeHumanReviewOnly:
		decision.Decision = DecisionHumanReview
		decision.Reason = "human_review_only_policy"
	case ModeStatusOnlyGreenLane:
		if eligibility == "green_auto_candidate" {
			decision.Decision = DecisionStatusDryRun
			decision.Reason = "green_candidate_status_only_dry_run"
		} else {
			decision.Decision = DecisionHumanReview
			decision.Reason = "non_green_candidate_requires_review"
		}
	case ModeAutoGreenLane:
		if eligibility == "green_auto_candidate" {
			decision.Decision = DecisionAutoGreenDryRun
			decision.Reason = "green_candidate_auto_dry_run_only"
		} else if eligibility == "amber_human_review" {
			decision.Decision = DecisionHumanReview
			decision.Reason = "amber_candidate_requires_review"
		} else {
			decision.Reason = "non_green_candidate_blocked"
		}
	default:
		decision.Reason = "blocked_policy"
	}
	if policy.CallbackTransport == TransportReal {
		decision.Reason += "_transport_real_requires_separate_sender_gate"
	}
	return decision
}

func normalizeMode(value string) string {
	switch strings.TrimSpace(value) {
	case ModeHumanReviewOnly:
		return ModeHumanReviewOnly
	case ModeStatusOnlyGreenLane:
		return ModeStatusOnlyGreenLane
	case ModeAutoGreenLane:
		return ModeAutoGreenLane
	case ModeEmergencyOff:
		return ModeEmergencyOff
	default:
		return ModeBlocked
	}
}

func normalizeTransport(value string) string {
	if strings.TrimSpace(value) == TransportReal {
		return TransportReal
	}
	return TransportDryRun
}
