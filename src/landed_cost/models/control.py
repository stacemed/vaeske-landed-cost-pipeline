"""8 CONTROL -- the tie-out panel. Per the workbook: 'Every difference must
read zero. If one does not, the number below it is wrong -- do not send the
file.'

A pipeline run should evaluate every ControlCheck before treating a
build-up as postable, using the same thresholds as the workbook (they vary
per check -- some allow no REVIEW tier at all, and check 10 is deliberately
wide because component purchases are expected to lead production by a
year or more).
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict

from .enums import CheckStatus


class ControlCheck(BaseModel):
    model_config = ConfigDict(frozen=True)

    check_number: int
    description: str
    built_up_value: Decimal
    source_value: Decimal
    ok_threshold: Decimal = Decimal("0.01")
    review_threshold: Decimal | None = Decimal("250")

    @property
    def difference(self) -> Decimal:
        return (self.built_up_value - self.source_value).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    @property
    def status(self) -> CheckStatus:
        magnitude = abs(self.difference)
        if magnitude < self.ok_threshold:
            return CheckStatus.OK
        if self.review_threshold is not None and magnitude < self.review_threshold:
            return CheckStatus.REVIEW
        return CheckStatus.CHECK


def all_ok(checks: list[ControlCheck]) -> bool:
    """True only if every check is OK -- the gate before posting a 'final'
    number sheet.
    """
    return all(check.status is CheckStatus.OK for check in checks)
