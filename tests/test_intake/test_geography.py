"""Tests for configurable geographic coverage evidence."""

import pytest
from django.core.exceptions import ValidationError

from intake.models import TriagePolicy
from intake.services.triage.geography import (
    Coverage,
    evaluate_coverage,
    parse_service_area,
)

POLYGON = {
    "type": "Polygon",
    "coordinates": [
        [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]],
        [[1, 1], [1, 2], [2, 2], [2, 1], [1, 1]],
    ],
}


def test_coverage_respects_holes_boundaries_and_missing_locations() -> None:
    """A pin's location is coverage evidence, not a scope decision."""
    area = parse_service_area(
        {"type": "Feature", "properties": {}, "geometry": POLYGON}
    )
    assert evaluate_coverage(area, 3, 3) == Coverage.INSIDE
    assert evaluate_coverage(area, 1.5, 1.5) == Coverage.OUTSIDE
    assert evaluate_coverage(area, 0, 0) == Coverage.BOUNDARY
    assert evaluate_coverage(area, None, 1) == Coverage.UNKNOWN
    assert evaluate_coverage(None, 1, 1) == Coverage.UNKNOWN
    assert evaluate_coverage(area, 100, 1) == Coverage.UNKNOWN


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"type": "Point", "coordinates": [0, 0]},
        {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1]]]},
        {"type": "Polygon", "coordinates": [[[0, 0], [3, 3], [3, 0], [0, 3], [0, 0]]]},
        {"type": "Polygon", "coordinates": [[[0, 0], [181, 0], [0, 1], [0, 0]]]},
        {
            "type": "Polygon",
            "coordinates": [[[170, 0], [-170, 0], [-170, 1], [170, 0]]],
        },
        {"type": "Polygon", "coordinates": [[[False, 0], [1, 0], [0, 1], [False, 0]]]},
        {
            "type": "Polygon",
            "coordinates": [[[10**1000, 0], [1, 0], [0, 1], [10**1000, 0]]],
        },
    ],
)
def test_invalid_coverage_cannot_pass_policy_validation(value: object) -> None:
    """Malformed and geographically ambiguous boundaries fail closed."""
    policy = TriagePolicy(version=1, name="Draft", service_area=value)
    with pytest.raises(ValidationError) as error:
        policy.clean()
    assert "service_area" in error.value.message_dict


def test_multipolygon_coverage() -> None:
    """Separate polygons can cover the same deployment."""
    area = parse_service_area(
        {"type": "MultiPolygon", "coordinates": [POLYGON["coordinates"]]}
    )
    assert evaluate_coverage(area, 3, 3) == Coverage.INSIDE
