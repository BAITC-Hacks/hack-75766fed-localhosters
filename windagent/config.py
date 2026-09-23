"""Shared configuration for the WindAgent data and modelling pipeline."""
from __future__ import annotations

import os


SCADA_TZ = "Etc/GMT-6"
SCADA_TZ_OFFSET_HOURS = 6

HOURLY_LABEL = os.getenv("HOURLY_LABEL", "left").lower()
if HOURLY_LABEL not in {"left", "right"}:
    raise ValueError("HOURLY_LABEL must be 'left' or 'right'")

MIN_SAMPLES_PER_HOUR = int(os.getenv("MIN_SAMPLES_PER_HOUR", "4"))
if not 1 <= MIN_SAMPLES_PER_HOUR <= 6:
    raise ValueError("MIN_SAMPLES_PER_HOUR must be between 1 and 6")

