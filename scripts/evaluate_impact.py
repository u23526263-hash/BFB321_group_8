"""Repeatable 28-day comparison of reactive and StockWise replenishment rules.

This is a model experiment, not evidence collected from operating spaza shops.
It writes the result used in docs/impact_and_sustainability.md.
"""

import csv
import json
import math
import random
from pathlib import Path


SEED = 321
DAYS = 28
SKU_COUNT = 20
# Both policies open with the same stock: ceil(daily_mean * OPENING_COVER) units per SKU.
OPENING_COVER = 3.2


def simulate(method: str, seed: int = SEED, opening_cover: float = OPENING_COVER) -> dict:
    rng = random.Random(seed)
    products = []
    for index in range(SKU_COUNT):
        # A small-shop demand profile: most SKUs sell below two units per day.
        daily_mean = 0.6 + (index % 6) * 0.22
        pack = [4, 6, 8, 10, 12][index % 5]
        cost = 7.5 + (index % 8) * 5.5
        lead = 1 + index % 2
        products.append(
            {
                "d": daily_mean,
                "pack": pack,
                "cost": cost,
                "lead": lead,
                "stock": math.ceil(daily_mean * opening_cover),
                "pipeline": [],
            }
        )

    stockout_days = 0
    emergency_trips = 0
    emergency_trip_days = 0
    constraint_breaches = 0
    cash_breaches = 0
    storage_breach_days = 0
    pack_violations = 0
    inventory_values = []
    cash_budget = 2500.0
    storage_capacity = 600

    for day in range(DAYS):
        for product in products:
            arriving = sum(qty for due, qty in product["pipeline"] if due == day)
            product["stock"] += arriving
            product["pipeline"] = [(due, qty) for due, qty in product["pipeline"] if due > day]

        for product in products:
            demand = max(0, round(rng.gauss(product["d"], 0.85)))
            sold = min(product["stock"], demand)
            product["stock"] -= sold
            if sold < demand:
                stockout_days += 1

        if method == "reactive":
            daily_cost = 0.0
            restocked_today = False
            for product in products:
                if product["stock"] == 0:
                    emergency_trips += 1
                    restocked_today = True
                    # Reactive buying tends to use a larger "catch-up" quantity after a stockout.
                    quantity = product["pack"] * math.ceil((product["d"] * 9) / product["pack"])
                    if quantity % product["pack"] != 0:
                        pack_violations += 1
                    daily_cost += quantity * product["cost"]
                    product["stock"] += quantity
            if restocked_today:
                emergency_trip_days += 1
            if daily_cost > cash_budget:
                constraint_breaches += 1
            if daily_cost > 2500:
                cash_breaches += 1
        elif day % 3 == 0:
            remaining_cash = cash_budget - 40
            used_storage = sum(product["stock"] for product in products)
            remaining_storage = storage_capacity - used_storage
            basket = []
            for product in sorted(products, key=lambda item: item["stock"] / item["d"]):
                on_order = sum(qty for _, qty in product["pipeline"])
                target = product["d"] * (product["lead"] + 3 + 1)
                gap = max(0, target - product["stock"] - on_order)
                quantity = product["pack"] * math.ceil(gap / product["pack"]) if gap else 0
                pack_cost = product["pack"] * product["cost"]
                allocated = 0
                while allocated < quantity and remaining_cash >= pack_cost and remaining_storage >= product["pack"]:
                    allocated += product["pack"]
                    remaining_cash -= pack_cost
                    remaining_storage -= product["pack"]
                if allocated:
                    basket.append((product, allocated))
            for product, quantity in basket:
                if quantity % product["pack"] != 0:
                    pack_violations += 1
                product["pipeline"].append((day + product["lead"], quantity))
            if basket:
                basket_spend = sum(quantity * product["cost"] for product, quantity in basket)
                if basket_spend + 40 > 2500:
                    cash_breaches += 1

        on_hand_units = sum(product["stock"] for product in products)
        if on_hand_units > storage_capacity:
            storage_breach_days += 1
        inventory_values.append(sum(product["stock"] * product["cost"] for product in products))

    availability = 100 * (1 - stockout_days / (DAYS * SKU_COUNT))
    return {
        "stockout_sku_days": stockout_days,
        "emergency_trips": emergency_trips,
        "emergency_collections": emergency_trips,
        "emergency_trip_days": emergency_trip_days,
        "average_stock_value": round(sum(inventory_values) / len(inventory_values), 2),
        "constraint_breaches": constraint_breaches,
        "cash_breaches": cash_breaches,
        "storage_breach_days": storage_breach_days,
        "pack_violations": pack_violations,
        "availability_percent": round(availability, 1),
    }


def _write_json(path: Path, payload: dict) -> None:
    """Write JSON using CRLF and no trailing newline, matching the committed results file."""
    text = json.dumps(payload, indent=2).replace("\n", "\r\n")
    path.write_bytes(text.encode("utf-8"))


def main():
    project_root = Path(__file__).resolve().parents[1]
    output_dir = project_root / "docs" / "generated"
    output_dir.mkdir(parents=True, exist_ok=True)
    results = {"reactive": simulate("reactive"), "stockwise": simulate("stockwise")}
    _write_json(output_dir / "impact_results.json", results)
    with (output_dir / "impact_results.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["metric", "reactive_baseline", "stockwise_rule"])
        for metric in results["reactive"]:
            writer.writerow([metric, results["reactive"][metric], results["stockwise"][metric]])
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
