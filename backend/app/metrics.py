"""
Metric catalog: every metric the platform reports, with its unit and how a day's
values combine into one daily number.

Two kinds:
  - "reading": an individual measurement stored in health_observations (weight at
    07:12, a blood pressure reading, ...). Many per day are normal.
  - "derived": calculated by the daily_health_summary view from detailed data
    (individual coughs in cough_events). Never written by hand.

Units are UCUM (the unit syntax used by FHIR/HL7); LOINC codes are given where one
exists, so a later export to FHIR or an EHR is a mapping exercise rather than a
redesign. Add new metrics here before writing them.
"""
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Metric:
    code: str
    unit: str
    description: str
    kind: Literal["reading", "derived"]
    # How several values on one day become the daily number in reports.
    daily: Literal["sum", "avg", "max", "last"]
    loinc: str | None = None


_METRICS = [
    # ── Derived from individual coughs, dated by the morning the night ended ─────
    Metric("cough.count", "{count}", "Coughs, excluding ones the user rejected", "derived", "sum"),
    Metric("cough.rate", "{count}/h", "Coughs per monitored hour", "derived", "avg"),
    Metric("cough.bouts", "{count}", "Coughing fits (coughs grouped by short gaps)", "derived", "sum"),
    Metric("sneeze.count", "{count}", "Sneezes, excluding ones the user rejected", "derived", "sum"),
    Metric("snore.duration", "min", "Minutes inside snoring episodes", "derived", "sum"),
    Metric("monitoring.duration", "h", "Hours the microphone was actually listening", "derived", "sum"),

    # ── Individual readings ──────────────────────────────────────────────────────
    Metric("body.weight", "kg", "Body weight", "reading", "avg", loinc="29463-7"),
    Metric("bp.systolic", "mm[Hg]", "Systolic blood pressure", "reading", "avg", loinc="8480-6"),
    Metric("bp.diastolic", "mm[Hg]", "Diastolic blood pressure", "reading", "avg", loinc="8462-4"),
    Metric("heart.rate", "/min", "Heart rate", "reading", "avg", loinc="8867-4"),
    Metric("body.temperature", "Cel", "Body temperature", "reading", "max", loinc="8310-5"),
    Metric("spo2", "%", "Oxygen saturation", "reading", "avg", loinc="59408-5"),
    Metric("activity.steps", "{steps}", "Steps", "reading", "sum", loinc="55423-8"),
    # Entered by the user until a device reports them. Sleep here is what the user says
    # they slept; monitoring.duration is how long the microphone listened.
    Metric("sleep.duration", "h", "Hours slept, as reported by the user", "reading", "sum", loinc="93832-4"),
    Metric("medication.taken", "{count}", "Medication doses taken", "reading", "sum"),
    Metric("medication.planned", "{count}", "Medication doses planned for the day", "reading", "sum"),
]

METRICS: dict[str, Metric] = {m.code: m for m in _METRICS}
READING_METRICS = {code for code, m in METRICS.items() if m.kind == "reading"}


def unit_for(code: str) -> str:
    """Raises KeyError for an unregistered metric — on purpose, so a typo can't
    silently create a new metric nobody reports on."""
    return METRICS[code].unit
