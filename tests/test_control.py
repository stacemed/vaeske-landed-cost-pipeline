from decimal import Decimal

from landed_cost.models import CheckStatus, ControlCheck
from landed_cost.models.control import all_ok


def test_check_within_ok_threshold():
    check = ControlCheck(
        check_number=6,
        description="Overhead absorbed = pool",
        built_up_value=Decimal("11522.97"),
        source_value=Decimal("11522.97"),
    )
    assert check.difference == Decimal("0.00")
    assert check.status is CheckStatus.OK


def test_check_7_qbo_additions_lands_in_review_like_the_real_workbook():
    # 8 CONTROL row 11, real numbers -- a $1.10 gap the workbook itself
    # flags REVIEW rather than OK or a hard CHECK failure.
    check = ControlCheck(
        check_number=7,
        description="QBO additions = QuickReport",
        built_up_value=Decimal("237139.87"),
        source_value=Decimal("237140.97"),
    )
    assert check.difference == Decimal("-1.10")
    assert check.status is CheckStatus.REVIEW


def test_check_10_components_uses_a_deliberately_wide_threshold():
    # 8 CONTROL row 14: components are EXPECTED to differ (this year's
    # purchases feed next year's production), so the workbook uses a
    # threshold wide enough that this never blocks a run.
    check = ControlCheck(
        check_number=10,
        description="Components",
        built_up_value=Decimal("-138.19"),
        source_value=Decimal("0.00"),
        ok_threshold=Decimal("999999"),
        review_threshold=None,
    )
    assert check.status is CheckStatus.OK


def test_check_without_review_tier_goes_straight_to_check():
    check = ControlCheck(
        check_number=9,
        description="Units allocated = units on the prep sheets",
        built_up_value=Decimal("100"),
        source_value=Decimal("50"),
        review_threshold=None,
    )
    assert check.status is CheckStatus.CHECK


def test_all_ok_requires_every_check_to_pass():
    passing = ControlCheck(
        check_number=1,
        description="a",
        built_up_value=Decimal(1),
        source_value=Decimal(1),
    )
    failing = ControlCheck(
        check_number=2,
        description="b",
        built_up_value=Decimal(1),
        source_value=Decimal(500),
    )
    assert all_ok([passing]) is True
    assert all_ok([passing, failing]) is False
