package sendcontrol

import "testing"

func TestDefaultPolicyBlocksEverything(t *testing.T) {
	decision := Evaluate(Policy{}, Candidate{EligibilityStatus: "green_auto_candidate", GatePassed: true, OwnerApproved: true, CallbackApproved: true})
	if decision.Decision != DecisionBlocked || decision.EffectiveMode != ModeBlocked {
		t.Fatalf("default policy must block, got %#v", decision)
	}
}

func TestEmergencyOffOverridesGreenLane(t *testing.T) {
	decision := Evaluate(
		Policy{Mode: ModeAutoGreenLane, EmergencyOff: true},
		Candidate{EligibilityStatus: "green_auto_candidate", GatePassed: true, OwnerApproved: true, CallbackApproved: true},
	)
	if decision.Decision != DecisionEmergencyOff || decision.Reason != "emergency_off_override" {
		t.Fatalf("emergency off did not dominate: %#v", decision)
	}
}

func TestAutoGreenLaneRequiresEveryGate(t *testing.T) {
	cases := []Candidate{
		{EligibilityStatus: "green_auto_candidate", GatePassed: false, OwnerApproved: true, CallbackApproved: true},
		{EligibilityStatus: "green_auto_candidate", GatePassed: true, OwnerApproved: false, CallbackApproved: true},
		{EligibilityStatus: "green_auto_candidate", GatePassed: true, OwnerApproved: true, CallbackApproved: false},
		{EligibilityStatus: "amber_human_review", GatePassed: true, OwnerApproved: true, CallbackApproved: true},
	}
	for _, candidate := range cases {
		decision := Evaluate(Policy{Mode: ModeAutoGreenLane}, candidate)
		if decision.Decision == DecisionAutoGreenDryRun {
			t.Fatalf("unsafe auto decision for candidate %#v: %#v", candidate, decision)
		}
	}
}

func TestAutoGreenLaneOnlyCreatesDryRunDecision(t *testing.T) {
	decision := Evaluate(
		Policy{Mode: ModeAutoGreenLane, CallbackTransport: TransportDryRun},
		Candidate{EligibilityStatus: "green_auto_candidate", GatePassed: true, OwnerApproved: true, CallbackApproved: true},
	)
	if decision.Decision != DecisionAutoGreenDryRun || decision.Transport != TransportDryRun {
		t.Fatalf("expected dry-run auto decision, got %#v", decision)
	}
}
