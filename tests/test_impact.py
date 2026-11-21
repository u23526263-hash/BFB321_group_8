import importlib.util
import json
import random
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "evaluate_impact.py"
RESULTS = ROOT / "docs" / "generated" / "impact_results.json"


def _load_evaluate_impact():
    spec = importlib.util.spec_from_file_location("evaluate_impact", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def evaluate_impact():
    return _load_evaluate_impact()


def _sensitivity_run(payload, opening_cover):
    matches = [
        run for run in payload["sensitivity"]["runs"] if run["opening_cover"] == opening_cover
    ]
    assert len(matches) == 1
    return matches[0]


def test_seed_321_headline_numbers(evaluate_impact):
    reactive = evaluate_impact.simulate("reactive")
    stockwise = evaluate_impact.simulate("stockwise")

    assert reactive["stockout_sku_days"] == 18
    assert reactive["emergency_collections"] == 56
    assert reactive["emergency_trips"] == reactive["emergency_collections"]
    assert reactive["emergency_trip_days"] == 23
    assert reactive["average_stock_value"] == 3507.05
    assert reactive["availability_percent"] == 96.8
    assert reactive["cash_breaches"] == 0
    assert reactive["storage_breach_days"] == 0
    assert reactive["pack_violations"] == 0
    assert reactive["constraint_breaches"] == 0

    assert stockwise["stockout_sku_days"] == 10
    assert stockwise["emergency_collections"] == 0
    assert stockwise["emergency_trips"] == stockwise["emergency_collections"]
    assert stockwise["emergency_trip_days"] == 0
    assert stockwise["average_stock_value"] == 3117.73
    assert stockwise["availability_percent"] == 98.2
    assert stockwise["cash_breaches"] == 0
    assert stockwise["storage_breach_days"] == 0
    assert stockwise["pack_violations"] == 0
    assert stockwise["constraint_breaches"] == 0

    saved = json.loads(RESULTS.read_text(encoding="utf-8"))
    assert saved["reactive"] == reactive
    assert saved["stockwise"] == stockwise


def test_both_policies_see_the_same_demand_path(evaluate_impact, monkeypatch):
    sequences = []

    class RecordingRandom(random.Random):
        def __init__(self, seed):
            super().__init__(seed)
            self.draws = []
            sequences.append(self.draws)

        def gauss(self, mu, sigma):
            value = super().gauss(mu, sigma)
            self.draws.append((mu, sigma, value))
            return value

    monkeypatch.setattr(evaluate_impact.random, "Random", RecordingRandom)
    evaluate_impact.simulate("reactive", seed=321, opening_cover=3.2)
    evaluate_impact.simulate("stockwise", seed=321, opening_cover=4.5)

    assert len(sequences) == 2
    assert sequences[0] == sequences[1]
    assert len(sequences[0]) == 28 * 20


def test_every_stockwise_order_is_a_whole_number_of_packs(evaluate_impact):
    orders = []
    for opening_cover in (3.2, 4.5):
        for seed in (321, *range(1, 31)):
            evaluate_impact.simulate(
                "stockwise",
                seed=seed,
                opening_cover=opening_cover,
                order_log=orders,
            )

    assert orders
    assert all(quantity > 0 and quantity % pack == 0 for pack, quantity in orders)


def test_results_json_contains_sensitivity_section():
    payload = json.loads(RESULTS.read_text(encoding="utf-8"))
    assert "sensitivity" in payload

    cover_32 = _sensitivity_run(payload, 3.2)
    assert len(cover_32["per_seed"]) == 30
    assert cover_32["seeds_with_at_least_20_percent_reduction"] == 27
    assert cover_32["median_reduction_percent"] == 58.0
    assert cover_32["min_reduction_percent"] == -14.3
    assert cover_32["min_reduction_seed"] == 12
    assert cover_32["max_reduction_percent"] == 84.6
    assert cover_32["total_stockout_sku_days"] == {"reactive": 550, "stockwise": 258}
    assert cover_32["seeds_stock_value_at_or_below_baseline"] == 29
    assert cover_32["stockwise_breach_events"] == 0
    assert cover_32["stockwise_emergency_collections"] == 0

    cover_45 = _sensitivity_run(payload, 4.5)
    assert cover_45["seeds_with_at_least_20_percent_reduction"] == 30
    assert cover_45["median_reduction_percent"] == 80.5
