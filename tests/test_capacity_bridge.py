"""Capacity bridge: power → units.

units = (total_power_gw × 1e9) / (power_per_gpu_watts × PUE)
For 1.2 GW, 1,000 W/GPU, PUE 1.3:
    1.2e9 / (1000 × 1.3) = 1.2e9 / 1300 = 923,076.92 → int 923,076.
"""

from __future__ import annotations

import pytest

from deal_copilot.economics_engine import bridge_unit_schedule
from deal_copilot.schemas import CapacityBridgeInputs, DealAssumptions


def test_derived_units_hand_value():
    bridge = CapacityBridgeInputs(total_power_gw=1.2, power_per_gpu_watts=1000.0, pue=1.3)
    assert bridge.derived_units() == 923_076


def test_bridge_schedule_sums_to_derived_total():
    bridge = CapacityBridgeInputs(total_power_gw=1.2, power_per_gpu_watts=1000.0, pue=1.3)
    a = DealAssumptions(capacity_bridge=bridge)
    sched = bridge_unit_schedule(a, 12)
    assert len(sched) == 12
    assert sum(sched) == pytest.approx(923_076.0, rel=1e-9)


def test_no_bridge_yields_zero_schedule():
    a = DealAssumptions()  # capacity_bridge is None (unit-denominated mode)
    assert bridge_unit_schedule(a, 4) == [0.0, 0.0, 0.0, 0.0]
