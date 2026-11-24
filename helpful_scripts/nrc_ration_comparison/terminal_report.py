"""Summarize the extracted RuFaS results for the terminal and JSON."""

from collections import defaultdict
from itertools import combinations
from statistics import mean, median

from .comparison_report import compare_runs, ratio, total
from .comparison_report_summary import number, percent, validation_rows


def lactation_diet(run, animal_days):
    ingredients = defaultdict(list)
    for row in run["composition"]:
        if row["group"] == "LAC_COW":
            ingredients[row["ingredient_id"]].append(row)
    for key, rows in sorted(ingredients.items(), key=lambda item: int(item[0])):
        mass = total(row["applied_kg_dm_pen"] for row in rows)
        if mass != 0:
            yield {
                "method": run["run"],
                "ingredient_id": key,
                "name": rows[0]["name"],
                "kg_dm_per_animal_day": ratio(mass, animal_days),
                "applied_usd": total(row["applied_usd"] for row in rows),
            }


def summarize(runs, wall_seconds):
    economics, performance, diets, differences = [], [], [], []
    for run in runs:
        label = run["run"]
        final = run["daily"][-1]
        lac = [row for row in run["pens"] if row["group"] == "LAC_COW"]
        animal_days = total(row["animals"] for row in lac)
        cost = final["cumulative_applied_usd"]
        economics.append(
            {
                "method": label,
                "days": len(run["daily"]),
                "applied_usd": cost,
                "applied_usd_per_day": ratio(cost, len(run["daily"])),
                "lactation_usd_per_animal_day": ratio(total(row["applied_usd"] for row in lac), animal_days),
                "applied_usd_per_kg_milk": ratio(cost, final["cumulative_milk_kg"]),
                "milk_kg": final["cumulative_milk_kg"],
                "applied_dm_kg": final["cumulative_applied_dm_kg"],
            }
        )
        attempts = run["attempts"]
        seconds = [row.get("optimization_seconds") for row in attempts]
        gaps = [row["gap_percent"] for row in attempts if row["success"] and row.get("gap_percent") is not None]
        successes = sum(row["success"] is True for row in attempts)
        failures = sum(row["success"] is False for row in attempts)
        sum_seconds = total(seconds)
        performance.append(
            {
                "method": label,
                "simulation_wall_seconds": wall_seconds.get(label),
                "optimization_seconds": sum_seconds,
                "optimization_mean_seconds": ratio(sum_seconds, len(seconds)),
                "optimization_median_seconds": median(seconds) if sum_seconds is not None else None,
                "attempts": len(attempts) if attempts else None,
                "successes": successes if attempts else None,
                "failures": failures if attempts else None,
                "success_percent": ratio(successes * 100, len(attempts)),
                "solver_calls": total(row.get("solver_calls") for row in attempts),
                "gap_mean_percent": mean(gaps) if gaps else None,
                "gap_median_percent": median(gaps) if gaps else None,
            }
        )
        diets.extend(lactation_diet(run, animal_days))
    for base, other in combinations(runs, 2):
        last = compare_runs(base, other, "daily")[-1]
        differences.append(
            {
                "baseline": base["run"],
                "comparison": other["run"],
                "applied_usd_delta": last["cumulative_applied_usd_delta"],
                "applied_usd_delta_pct": last["cumulative_applied_usd_delta_pct"],
            }
        )
    return dict(
        economics=economics,
        differences=differences,
        performance=performance,
        lactation_validation=validation_rows(runs),
        lactation_diet=diets,
    )


def print_table(headers, rows):
    formatted = [headers] + [tuple("—" if value is None else str(value) for value in row) for row in rows]
    widths = [max(map(len, column)) for column in zip(*formatted, strict=True)]
    print("  ".join(text.ljust(width) for text, width in zip(headers, widths, strict=True)).rstrip())
    print("  ".join("-" * width for width in widths))
    for row in formatted[1:]:
        print("  ".join(text.ljust(width) for text, width in zip(row, widths, strict=True)).rstrip())


def metrics_table(rows, fields):
    print_table(
        ("Métrica", *(row["method"] for row in rows)),
        [
            (title, *(formatter(row[key]) if row[key] is not None else None for row in rows))
            for key, title, formatter in fields
        ],
    )


def show(summary):
    print("\nEconomia · alimentação fornecida aos preços de entrada (US$)")
    metrics_table(
        summary["economics"],
        (
            ("applied_usd", "Custo total do rebanho", number),
            ("applied_usd_per_day", "Custo médio do rebanho/dia", number),
            ("lactation_usd_per_animal_day", "Custo médio/vaca em lactação/dia", number),
            ("applied_usd_per_kg_milk", "Custo do rebanho/kg de leite", lambda value: number(value, 6)),
            ("milk_kg", "Leite total (kg)", number),
            ("applied_dm_kg", "MS fornecida ao rebanho (kg)", number),
        ),
    )
    if summary["differences"]:
        print("\nDiferença no custo total (comparação menos base)")
        print_table(
            ("Base", "Comparação", "US$", "% da base"),
            [
                (
                    r["baseline"],
                    r["comparison"],
                    number(r["applied_usd_delta"]),
                    percent(r["applied_usd_delta_pct"], signed=True),
                )
                for r in summary["differences"]
            ],
        )
    print("\nDesempenho · todos os lotes com tentativas registradas")
    metrics_table(
        summary["performance"],
        (
            ("simulation_wall_seconds", "Simulação, tempo de parede (s)", number),
            ("optimization_seconds", "Otimização total (s)", number),
            ("optimization_mean_seconds", "Tempo médio/tentativa (s)", number),
            ("optimization_median_seconds", "Tempo mediano/tentativa (s)", number),
            ("attempts", "Tentativas de formulação", str),
            ("successes", "Sucessos registrados", str),
            ("failures", "Falhas registradas", str),
            ("success_percent", "Taxa de sucesso", percent),
            ("solver_calls", "Chamadas ao solver", str),
            ("gap_mean_percent", "Gap médio (tentativas com gap)", percent),
            ("gap_median_percent", "Gap mediano (tentativas com gap)", percent),
        ),
    )
    print("\nValidação nutricional · lactação")
    fields = ("Método", "Critério nutricional", "Aprovadas", "Rejeitadas", "Sem resultado nesse critério")
    print_table(fields, [[row[field] for field in fields] for row in summary["lactation_validation"]])
    print("\nIngredientes fornecidos · lactação")
    print_table(
        ("Método", "ID", "Ingrediente", "kg MS/vaca/dia", "US$ acumulado"),
        [
            (
                row["method"],
                row["ingredient_id"],
                row["name"],
                number(row["kg_dm_per_animal_day"]),
                number(row["applied_usd"]),
            )
            for row in summary["lactation_diet"]
        ],
    )
    print("\nCustos calculados sobre alimentação fornecida. As trajetórias simuladas podem divergir.")
