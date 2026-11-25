"""Representative fictional evaluation scenarios demonstrating engine behaviour."""

from __future__ import annotations

from pydantic import BaseModel

from triage_engine.schemas import ContextInput, LocationInput


class EvaluationScenario(BaseModel):
    id: str
    title: str
    scenario_type: str
    summary: str
    recommended_profiles: list[str]
    expected_highlights: list[str]
    description: str
    location: LocationInput | None = None
    context: ContextInput | None = None


EVALUATION_SCENARIOS: list[EvaluationScenario] = [
    EvaluationScenario(
        id="comparison_ceiling_leak_electrical",
        title="Ceiling Water Leak Near Electrical Socket (Cross-Org Showcase)",
        scenario_type="cross_org_comparison",
        summary=(
            "Demonstrates identical safety escalation across organisations while category and team "
            "routing adapt to StreetFix vs. Campus Facilities configurations."
        ),
        recommended_profiles=["streetfix", "campus_facilities"],
        expected_highlights=[
            "Both organisations trigger SYS_ELECTRICAL_WATER_HAZARD critical escalation.",
            "StreetFix routes to Civic Buildings / Electrical; Campus Facilities routes to Building Electrical or Plumbing MEP.",
            "Mandatory human review enforced regardless of model confidence.",
        ],
        description=(
            "Water leaking through the ceiling near an electrical socket. There is steady dripping running "
            "down the plaster wall directly above a double wall outlet."
        ),
        location=LocationInput(
            free_text="Ground floor corridor beside main stairwell",
            address="Block B, Ground Floor",
            zone_or_ward="Central Precinct",
        ),
        context=ContextInput(
            reporter_role="staff",
            channel="web_form",
            observed_at="2026-11-24T08:40:00Z",
            media_attached=True,
        ),
    ),
    EvaluationScenario(
        id="straightforward_pothole",
        title="Straightforward Arterial Carriageway Pothole",
        scenario_type="straightforward",
        summary="Clear description with exact location mapping directly to highways category and team.",
        recommended_profiles=["streetfix"],
        expected_highlights=[
            "Maps clearly to potholes_roads and Highways & Carriageway Maintenance.",
            "Verbatim excerpt verified against input text.",
        ],
        description=(
            "There is a deep pothole approximately 45cm wide and 10cm deep in the northbound lane "
            "just before the High Street and Mill Lane traffic lights. Two cars hit it this morning."
        ),
        location=LocationInput(
            free_text="Northbound carriageway 20m south of Mill Lane junction",
            address="142 High Street",
            zone_or_ward="North Ward",
        ),
        context=ContextInput(
            reporter_role="resident",
            channel="web_form",
            media_attached=True,
        ),
    ),
    EvaluationScenario(
        id="ambiguous_pavement_branch",
        title="Ambiguous Branch, Bollard & Streetlight Incident",
        scenario_type="ambiguous",
        summary="Overlapping tree obstruction, damaged street furniture, and flickering lighting.",
        recommended_profiles=["streetfix", "campus_facilities"],
        expected_highlights=[
            "Moderate/high decision uncertainty with alternative candidate categories listed.",
            "Human review triggered due to multi-category ambiguity.",
        ],
        description=(
            "A large tree branch came down overnight beside the footpath cut-through, knocking a "
            "bollard sideways, and the nearby lamp column is now flickering dimly."
        ),
        location=LocationInput(free_text="Footpath cut-through behind Station Road car park"),
        context=ContextInput(reporter_role="resident", channel="chatbot"),
    ),
    EvaluationScenario(
        id="safety_critical_sparking_lamp",
        title="Exposed Sparking Streetlamp Wiring by School Crossing",
        scenario_type="safety_critical",
        summary="High-risk electrical hazard near a school crossing requiring immediate escalation.",
        recommended_profiles=["streetfix"],
        expected_highlights=[
            "Deterministic SYS_ELECTRICAL_WATER_HAZARD forces P1 Emergency floor.",
            "Immediate make-safe guidance and mandatory human review enforced.",
        ],
        description=(
            "The inspection door on lamppost #14 right next to Oakwood Primary school crossing has "
            "been kicked off. Exposed wires are sparking in the rain puddle on the kerb."
        ),
        location=LocationInput(
            free_text="Outside Oakwood Primary School crossing",
            address="Oakwood Avenue",
        ),
        context=ContextInput(reporter_role="parent", channel="web_form", recurring_issue=False),
    ),
    EvaluationScenario(
        id="incomplete_park_report",
        title="Incomplete Vague Report Missing Location & Defect Details",
        scenario_type="incomplete",
        summary="Tests abstention / insufficient evidence handling and missing information requests.",
        recommended_profiles=["streetfix", "campus_facilities"],
        expected_highlights=[
            "Abstains or marks evidence quality as insufficient.",
            "Generates targeted missing-information questions without inventing facts.",
        ],
        description="It's broken near the park, please fix ASAP.",
        location=None,
        context=ContextInput(reporter_role="resident", channel="chatbot"),
    ),
    EvaluationScenario(
        id="conflicting_underpass_flooding",
        title="Contradictory Underpass Flooding Report",
        scenario_type="conflicting",
        summary="Contains contradictory claims about active flooding versus completely dry conditions.",
        recommended_profiles=["streetfix"],
        expected_highlights=[
            "Deterministic contradiction detector flags conflicting water statements.",
            "Human review required; AI does not treat conflicting claims as certain.",
        ],
        description=(
            "Urgent flooding in the pedestrian underpass with deep standing water blocking the steps. "
            "Actually walked back past ten minutes later and it is completely dry with no water visible, "
            "though there is a strong drain smell."
        ),
        location=LocationInput(free_text="Railway Station pedestrian underpass"),
    ),
    EvaluationScenario(
        id="multi_category_flytip_crossing",
        title="Multi-Category Fly-Tipping Blocking Faded Crossing",
        scenario_type="multi_category",
        summary="Combines illegal waste dumping with obscured pedestrian signage and faded markings.",
        recommended_profiles=["streetfix"],
        expected_highlights=[
            "Primary category plus explicit alternative candidate categories.",
            "Priority criterion CRIT_SCHOOL_CROSSING / crossing visibility noted.",
        ],
        description=(
            "Someone dumped three wet mattresses and builders rubble right over the zebra crossing "
            "on King Street, and the crossing beacon sign has been knocked flat on the verge."
        ),
        location=LocationInput(address="King Street zebra crossing near No. 48"),
    ),
    EvaluationScenario(
        id="unusual_delivery_noise",
        title="Out-of-Scope Private Delivery Noise Complaint",
        scenario_type="unusual",
        summary="Report outside configured infrastructure categories testing abstention & fallback routing.",
        recommended_profiles=["streetfix", "campus_facilities"],
        expected_highlights=[
            "Abstains from forcing an ill-fitting infrastructure category.",
            "Routes to fallback duty desk / helpdesk with human review required.",
        ],
        description=(
            "Private supermarket delivery vans are idling outside my bedroom window at 4:30 AM every "
            "Tuesday and playing loud radios while unloading crates."
        ),
        location=LocationInput(address="22 Elm Grove"),
    ),
    EvaluationScenario(
        id="negated_hazard_puddle",
        title="Negated Hazard Boundary Case (Rain Puddle, No Live Wires)",
        scenario_type="negated_hazard",
        summary="Verifies negation-aware deterministic safety avoids false critical escalation.",
        recommended_profiles=["streetfix"],
        expected_highlights=[
            "Records 'no live wires or sparking' under negated_or_uncertain_mentions (negated).",
            "Does not falsely escalate to P1 Emergency.",
        ],
        description=(
            "Large rainwater puddle pooling across the footpath beside a blocked kerb gully on Market Road. "
            "Inspected closely and confirmed there are no live wires or sparking equipment nearby."
        ),
        location=LocationInput(address="Market Road outside Library"),
    ),
]
