"""Extract auditable comparisons from saved RuFaS output without running a simulation."""

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

from RUFAS.biophysical.animal.animal_module_constants import AnimalModuleConstants as NRC
from RUFAS.biophysical.animal.ration.linear_ration_optimizer import _NRC_TOLERANCES

from .cli_three_day import read
from .cli_three_day_summary import PEN_DATA, indexed, ingredients, series_for

PEN = re.compile(r"AnimalModuleReporter\.report_ration_per_animal\.ration_per_animal_for_(.+)_PEN_(\d+)")
ATTEMPT = re.compile(r"(?:[^.]+\.)+ration_optimizer_attempt_pen_\d+")
PURCHASE = re.compile(r"FeedManager\.purchase_feed\.(.+)_(\d+)_cost")
MILK = "report_herd_statistics_data.daily_milk_production"
REUSE = "Previous ration used because automated ration formulation failed"
METRICS = (
    "applied_usd_per_animal",
    "applied_usd",
    "cumulative_applied_usd",
    "milk_kg",
    "cumulative_milk_kg",
    "usd_per_kg_milk",
    "applied_dm_kg",
    "cumulative_applied_dm_kg",
    "animals",
    "formulated_usd_per_animal",
    "optimization_s",
    "gap_percent",
    "purchase_usd",
    "cumulative_purchase_usd",
)


def ratio(value, denominator):
    return value / denominator if value is not None and denominator else None


def total(values):
    values = list(values)
    return sum(values) if values and all(value is not None for value in values) else None


def subtract(left, right):
    return left - right if left is not None and right is not None else None


def close(left, right):
    return left is not None and right is not None and math.isclose(left, right, abs_tol=1e-6)


def price_of(amounts, prices):
    return total(0.0 if not kg else kg * prices[key] if key in prices else None for key, kg in amounts.items())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def day_series(series, name, issues):
    counts = Counter(info.get("simulation_day") for info in series["info_maps"])
    if len(series["values"]) != len(series["info_maps"]) or None in counts:
        raise ValueError(f"Série diária sem metadados temporais completos: {name}")
    duplicates = [day for day, count in counts.items() if count > 1]
    if duplicates:
        issues.append(f"{name}: dias duplicados excluídos {duplicates}")
    return {day: item for day, item in indexed(series).items() if counts[day] == 1}


def date_label(year, day):
    date = dt.date(year, 1, 1) + dt.timedelta(days=day - 1)
    if day < 1 or date.year != year:
        raise ValueError(f"Dia juliano inválido: {year}:{day}")
    return date.isoformat()


def date_index(data, issues):
    # Use simulation_day in the metadata even when JSON series are sparse or reordered.
    days = day_series(data["RufasTime.day"], "RufasTime.day", issues)
    years = day_series(data["RufasTime.calendar_year"], "RufasTime.calendar_year", issues)
    dates = {day: date_label(years[day]["value"], days[day]["value"]) for day in days.keys() & years.keys()}
    if len(dates) != len(days) or len(dates) != len(years):
        issues.append("Ano ou dia juliano ausente em marcadores de calendário.")
    counts = Counter(dates.values())
    if any(count > 1 for count in counts.values()):
        issues.append("Datas civis duplicadas nos marcadores de calendário, excluídas das comparações.")
    return {day: date for day, date in dates.items() if counts[date] == 1}


def read_catalog(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return {row["rufas_id"]: row for row in csv.DictReader(stream)}


def nrc_balance(requirements, supply, legacy, group, attempt, config, feed):
    """Reconstruct margins for reported diets when optimizer inputs are identifiable."""
    req, sup, legacy = requirements or {}, supply or {}, legacy or {}
    dm = sup.get("dm")
    ndf = ratio(sup.get("NDF"), dm)
    energy_keys = ("NE_maintenance_and_activity", "NE_lactation", "NE_growth")
    energy = [sup.get(key) for key in energy_keys]
    maintenance = total(req.get(k) for k in ("NEmaint_requirement", "NEa_requirement"))
    lactation = total(req.get(k) for k in ("NEl_requirement", "NEpreg_requirement"))
    growth = req.get("NEg_requirement")
    phosphorus = [req.get(k) for k in ("P_req", "P_req_process")]
    p_target = max(phosphorus) if None not in phosphorus else None
    mp = req.get("MP_requirement")
    dmi = req.get("DMIest_requirement")
    recipe = next((r for r in feed.get("rations", []) if r["animal_combination"] == group.lower()), {})
    predicted = recipe.get("intake_option") in (None, "predict_DMI")
    automated = attempt and attempt.get("backend_reason") != "user_defined_ration"
    first = attempt and attempt.get("attempt") == 1 and attempt.get("success")
    nrc = config.get("nutrient_standard") == "NRC"
    reconstruct = nrc and first and automated and dm is not None and dm > 0
    mp_max = mp * NRC.PROTEIN_UPPER_LIMIT_FACTOR if first and mp is not None else None
    bounds = (
        [dmi * (1 - NRC.DMI_CONSTRAINT_FRACTION), dmi * (1 + NRC.DMI_CONSTRAINT_FRACTION)]
        if first and predicted and dmi is not None
        else [None, None]
    )
    specs = (
        (
            "NE_total_constraint",
            "Mcal",
            max(energy) if None not in energy else None,
            total((maintenance, lactation, growth)),
            None,
            "min",
            "total_energy_difference",
        ),
        (
            "NE_maintenance_and_activity_constraint",
            "Mcal",
            energy[0],
            maintenance,
            None,
            "min",
            "maintenance_energy_difference",
        ),
        ("NE_lactation_constraint", "Mcal", energy[1], lactation, None, "min", "lactation_energy_difference"),
        ("NE_growth_constraint", "Mcal", energy[2], growth, None, "min", "growth_energy_difference"),
        (
            "calcium_constraint",
            "g",
            sup["calcium"] * 1000 if "calcium" in sup else None,
            req.get("Ca_requirement"),
            None,
            "min",
            "calcium_difference",
        ),
        (
            "phosphorus_constraint",
            "g",
            sup["phosphorus"] * 1000 if "phosphorus" in sup else None,
            p_target,
            None,
            "min",
            "phosphorus_difference",
        ),
        (
            "protein_constraint_lower",
            "g",
            sup.get("metabolizable_protein"),
            mp,
            None,
            "min",
            "metabolizable_protein_difference",
        ),
        (
            "protein_constraint_upper",
            "g",
            sup.get("metabolizable_protein"),
            mp,
            mp_max,
            "max",
            "metabolizable_protein_difference",
        ),
        (
            "NDF_constraint_lower",
            "% MS",
            None if ndf is None else ndf * 100,
            None,
            NRC.MINIMUM_RATION_NDF,
            "min",
            "ndf_percent_difference",
        ),
        (
            "NDF_constraint_upper",
            "% MS",
            None if ndf is None else ndf * 100,
            None,
            NRC.MAXIMUM_RATION_NDF,
            "max",
            "ndf_percent_difference",
        ),
        (
            "forage_NDF_constraint",
            "% MS",
            sup.get("forage_ndf_percent"),
            None,
            NRC.MINIMUM_RATION_FORAGE_NDF,
            "min",
            "forage_ndf_percent_difference",
        ),
        (
            "fat_constraint",
            "% MS",
            sup.get("fat_percentage"),
            None,
            NRC.MAXIMUM_RATION_FAT,
            "max",
            "fat_percent_difference",
        ),
        ("DMI_constraint_lower", "kg MS", dm, dmi, bounds[0], "min", "dry_matter_difference"),
        ("DMI_constraint_upper", "kg MS", dm, dmi, bounds[1], "max", "dry_matter_difference"),
    )
    rows = []
    for name, unit, offer, target, limit, direction, legacy_key in specs:
        applicable = (
            group == "LAC_COW"
            or group in {"GROWING", "CLOSE_UP", "GROWING_AND_CLOSE_UP"}
            and name not in {"NE_total_constraint", "NE_lactation_constraint"}
        )
        if limit is None and direction == "min" and not name.startswith("DMI_"):
            limit = target
        if not reconstruct or not applicable:
            limit = None
        margin = subtract(offer, limit) if direction == "min" else subtract(limit, offer)
        tolerance = _NRC_TOLERANCES[name] if margin is not None else None
        rows.append(
            dict(
                constraint=name,
                unit_per_animal_day=unit,
                offer=offer,
                nutritional_target=target,
                effective_limit=limit,
                direction=direction,
                offer_minus_target=subtract(offer, target),
                margin=margin,
                audit_tolerance=tolerance,
                audit_status=(None if margin is None else "atende" if margin >= -tolerance else "viola"),
                reporter_evaluation=legacy.get(legacy_key),
            )
        )
    return rows


def pen_milk(data, issues):
    records = series_for(data, "report_milk.milk_data_at_milk_update")["values"]
    seen = Counter((r["simulation_day"], r["cow_id"]) for r in records)
    bad_days = {key[0] for key, count in seen.items() if count > 1}
    if bad_days:
        issues.append(f"Duplicatas no leite individual, dias excluídos da agregação por lote: {sorted(bad_days)}")
    grouped = defaultdict(list)
    for row in records:
        if row["simulation_day"] not in bad_days:
            grouped[row["simulation_day"], row["pen_id"]].append(row["estimated_daily_milk_produced"])
    return {key: total(values) for key, values in grouped.items()}


def attempt_rows(data, dates, label, issues):
    records = [row for key, value in data.items() if ATTEMPT.fullmatch(key) for row in value["values"]]
    counts = Counter((r["simulation_day"], r["pen_id"], r["attempt"]) for r in records)
    rows = []
    for row in sorted(records, key=lambda r: (r["simulation_day"], r["pen_id"], r["attempt"])):
        day, pen, attempt = (row[k] for k in ("simulation_day", "pen_id", "attempt"))
        if counts[day, pen, attempt] > 1 or day not in dates:
            continue
        backend = row.get("backend")
        rows.append(
            dict(
                row,
                run=label,
                date=dates[day],
                solver="SLSQP" if backend == "slsqp" else row.get("nutritional_solver"),
                linear_nrc_approved=(row.get("nutritional_validation") == "approved") if backend == "pulp" else None,
                gap_percent=row["gap_achieved"] * 100 if row.get("gap_achieved") is not None else None,
            )
        )
    if len(rows) != len(records):
        issues.append("Tentativas duplicadas ou sem data foram excluídas. Totais dependem dos registros disponíveis.")
    return rows


def attach_trace(path, attempts, issues):
    if path is None:
        issues.append("Rastreamento por candidato indisponível. Diagnósticos usam a exportação principal.")
        return {}
    with path.open(encoding="utf-8-sig") as stream:
        traces = [json.loads(line) for line in stream if line.strip()]
    keys = ("simulation_day", "pen_id", "attempt")
    index = {tuple(row[k] for k in keys): row for row in attempts}
    counts = Counter(tuple(row[k] for k in keys) for row in traces)
    result = {}
    for trace in traces:
        key = tuple(trace[k] for k in keys)
        attempt = index.get(key)
        if counts[key] != 1 or not attempt or any(trace[k] != attempt[k] for k in ("backend", "success")):
            issues.append(f"Rastreamento incompatível ou duplicado para {key}.")
            continue
        if attempt["backend"] == "pulp" and any(
            trace.get(left) != attempt.get(right)
            for left, right in (
                ("selected_reference", "reference"),
                ("solver_calls", "solver_calls"),
                ("gap", "gap_achieved"),
                ("lower_bound", "lower_bound_usd_per_animal_day"),
            )
        ):
            issues.append(f"Rastreamento linear divergente para {key}.")
            continue
        result[key] = trace
        cases = [
            case
            for ref in trace.get("references", [])
            if ref["source"] == trace.get("selected_reference")
            for case in ref["cases"]
            if case["regime"] == trace.get("selected_case")
        ]
        checks = trace.get("applied_nrc_check")
        attempt["selected_lp_status"] = cases[0]["lp_status"] if len(cases) == 1 else None
        attempt["trace_backend_status_code"] = trace.get("status")
        check = None
        if checks:
            check = checks["unrounded"]
            attempt["slsqp_posthoc_nrc_pass"] = not check["violations"]
        elif len(cases) == 1:
            val = cases[0].get("validation") or {}
            repair = val.get("repair") or {}
            approved_quantities = repair.get("quantities") or val.get("rounded_quantities")
            if approved_quantities is not None and approved_quantities == trace.get("applied_quantities"):
                check = repair.get("validation") or val.get("rounded")
            attempt["trace_validation_quantities_match"] = (
                approved_quantities == trace["applied_quantities"] if approved_quantities is not None else None
            )
        if check:
            attempt["trace_residuals"] = check["residuals"]
            attempt["trace_violations"] = check["violations"]
    return result


def purchase_rows(data, dates, label):
    rows = []
    for key, series in data.items():
        match = PURCHASE.fullmatch(key)
        if match:
            for value, info in zip(series["values"], series["info_maps"], strict=True):
                day = info["simulation_day"]
                rows.append(
                    dict(
                        run=label,
                        simulation_day=day,
                        date=dates.get(day),
                        purchase_type=match[1],
                        ingredient_id=match[2],
                        purchase_usd=value,
                        reported_unit=info.get("units"),
                    )
                )
    return rows


def accumulate(rows, fields):
    # Missing observations invalidate later sums within a run or pen.
    sums = dict.fromkeys(fields, 0)
    for row in rows:
        for field in fields:
            sums[field] = total((sums[field], row.get(field)))
            row[f"cumulative_{field}"] = sums[field]


def extract_run(label, source, metadata, console=None, trace=None):
    data = read(source)
    entries = read(metadata)["files"]
    paths = {key: Path(item["path"]) for key, item in entries.items()}
    hashes = {key: digest(path) if path.is_file() else None for key, path in paths.items()}
    feed = read(paths["feed"])
    config = read(paths["config"])
    animal = read(paths["animal"])
    catalog = read_catalog(paths["user_feeds"])
    composition_key = "NASEM_Comp" if config.get("nutrient_standard") == "NASEM" else "NRC_Comp"
    composition = read_catalog(paths[composition_key])
    prices = {str(item["feed_type"]): item["purchased_feed_cost"] for item in feed["feeds"]}
    issues = []
    dates = date_index(data, issues)
    if not dates:
        raise ValueError(f"{source}: nenhum dia com calendário válido")
    expected_start = date_label(*map(int, config["start_date"].split(":")))
    expected_end = date_label(*map(int, config["end_date"].split(":")))
    start = dt.date.fromisoformat(expected_start)
    expected = {
        (start + dt.timedelta(days=i)).isoformat()
        for i in range((dt.date.fromisoformat(expected_end) - start).days + 1)
    }
    if expected != set(dates.values()):
        issues.append(
            f"Calendário divergente da configuração: faltam {sorted(expected - set(dates.values()))}, "
            f"extras {sorted(set(dates.values()) - expected)}"
        )
    seed = data.get("TaskManager.set_random_seed.random_seed", {}).get("values", [])
    if len(seed) != 1:
        issues.append("Semente única indisponível no JSON.")
    herd_milk = day_series(series_for(data, MILK), MILK, issues)
    herd_feed_name = "report_daily_herd_total_ration.ration_daily_feed_total_across_pens"
    herd_feed = day_series(series_for(data, herd_feed_name), herd_feed_name, issues)
    milk_by_pen = pen_milk(data, issues)
    for day, record in herd_milk.items():
        pen_total = total(value for (milk_day, _), value in milk_by_pen.items() if milk_day == day)
        if pen_total is not None and not close(pen_total, record["value"]):
            issues.append(f"Dia {day}: leite individual por lote diverge do total de leite do rebanho.")
    attempts = attempt_rows(data, dates, label, issues)
    by_pen = defaultdict(list)
    for row in attempts:
        by_pen[row["simulation_day"], row["pen_id"]].append(row)
    trace_index = attach_trace(trace, attempts, issues)
    purchases = purchase_rows(data, dates, label)
    if not attempts:
        issues.append("Nenhum diagnóstico de tentativa foi exportado. Frequência de formulação indisponível.")
    if not purchases:
        issues.append("Custos de aquisição indisponíveis no JSON (séries FeedManager.purchase_feed).")
    if console is not None:
        reuse = console.read_text(encoding="utf-8", errors="replace").count(REUSE)
    else:
        reuse = None
        issues.append(
            "Reaproveitamento após falha sem confirmação de log. Composição igual pode resultar de nova formulação."
        )
    pens, mixes, balances = [], [], []
    pen_keys = {(int(match[2]), match[1]) for key in data if (match := PEN.fullmatch(key))}
    for pen, group in sorted(pen_keys):
        names = {k: v.format(pen=pen, group=group) for k, v in PEN_DATA.items()}
        names["animals"] = f"report_daily_pen_total.number_of_animals_in_pen_{pen}_{group}"
        names["legacy"] = f"report_average_nutrient_evaluation_results.avg_eval_results_for_{group}_PEN_{pen}"
        series = {k: day_series(series_for(data, name), name, issues) for k, name in names.items()}
        for day, date in sorted(dates.items(), key=lambda item: item[1]):
            values = {k: index.get(day, {}).get("value") for k, index in series.items()}
            ration, applied = (ingredients(values[k] or {}) for k in ("ration", "feed"))
            if values["ration"] is None or values["feed"] is None or values["animals"] is None:
                issues.append(f"Lote {pen}, dia {day}: ração formulada, aplicada ou contagem indisponível.")
            animals = values["animals"]
            formulation_count = series["ration"].get(day, {}).get("info", {}).get("number_animals_in_pen")
            dm = total(applied.values())
            cost = price_of(applied, prices)
            formed_dm = total(ration.values())
            formed_cost = price_of(ration, prices)
            milk = milk_by_pen.get((day, pen))
            historical = by_pen[day, pen]
            success = next((r for r in reversed(historical) if r.get("success")), None)
            base = dict(
                run=label,
                date=date,
                simulation_day=day,
                day_number=day + 1,
                julian_day=dt.date.fromisoformat(date).timetuple().tm_yday,
                pen_id=pen,
                group=group,
            )
            consistent = None
            if ration and applied and animals is not None:
                consistent = all(
                    close(applied.get(key, 0), ration.get(key, 0) * animals) for key in applied.keys() | ration.keys()
                )
                if not consistent:
                    issues.append(f"Lote {pen}, dia {day}: composição formulada × animais do dia diverge da fornecida.")
            reported_cost = success.get("cost_usd_per_animal_day") if success else None
            if reported_cost is not None and not close(formed_cost, reported_cost):
                issues.append(f"Lote {pen}, dia {day}: custo formulado diverge do custo registrado na tentativa.")
            if values["ration"] is not None and not close(formed_dm, values["ration"].get("dry_matter_intake_total")):
                issues.append(f"Lote {pen}, dia {day}: MS formulada diverge da soma por ingrediente.")
            if values["feed"] is not None and not close(dm, values["feed"].get("dry_matter_intake_total")):
                issues.append(f"Lote {pen}, dia {day}: total de MS do lote diverge da soma por ingrediente.")
            for row in historical:
                trace_row = trace_index.get((day, pen, row["attempt"]), {})
                traced_applied = trace_row.get("applied_quantities")
                row["traced_quantities_match_reported"] = (
                    traced_applied == ration if traced_applied is not None else None
                )
                if row["traced_quantities_match_reported"] is False:
                    issues.append(f"Lote {pen}, dia {day}: a composição do rastreamento diverge da ração reportada.")
                is_success = row is success
                row.update(
                    formulated_cost_matches_report=(
                        close(formed_cost, reported_cost) if is_success and reported_cost is not None else None
                    ),
                    formula_times_animals_matches_applied=consistent if is_success else None,
                    accepted_cost_recorded=reported_cost is not None if is_success else False,
                )
            pens.append(
                dict(
                    base,
                    animals=animals,
                    animals_at_formulation=formulation_count,
                    applied_dm_kg=dm,
                    formulated_dm_kg_per_animal=formed_dm,
                    applied_usd=cost,
                    applied_usd_per_animal=ratio(cost, animals),
                    formulated_usd_per_animal=formed_cost,
                    milk_kg=milk,
                    usd_per_kg_milk=ratio(cost, milk),
                    optimization_s=total(r.get("optimization_seconds") for r in historical),
                    gap_percent=success.get("gap_percent") if success else None,
                    applied_composition_consistent=consistent,
                    attempts=len(historical),
                    failures=sum(r.get("success") is False for r in historical),
                    reformulations=sum(r["attempt"] > 1 for r in historical),
                )
            )
            for key in sorted(ration.keys() | applied.keys(), key=int):
                name = catalog.get(key, {})
                info = composition.get(key, {})
                dm_fraction = (
                    float(info["DM"]) / 100 if info.get("DM") and info.get("units", "").lower() == "kg" else None
                )
                applied_dm, formulated_dm = applied.get(key), ration.get(key)
                ingredient_cost = price_of({key: applied_dm}, prices) if applied_dm is not None else None
                if key not in catalog or key not in prices:
                    issues.append(f"Ingrediente {key}: nome ou preço de entrada ausente.")
                mixes.append(
                    dict(
                        base,
                        ingredient_id=key,
                        name=" ".join(filter(None, (name.get("Name"), name.get("feed_description")))) or None,
                        input_usd_per_kg_dm=prices.get(key),
                        dm_fraction=dm_fraction,
                        formulated_kg_dm_per_animal=formulated_dm,
                        formulated_kg_as_fed_per_animal=ratio(formulated_dm, dm_fraction),
                        formulated_usd_per_animal=(
                            price_of({key: formulated_dm}, prices) if formulated_dm is not None else None
                        ),
                        applied_kg_dm_pen=applied_dm,
                        applied_kg_dm_per_animal=ratio(applied_dm, animals),
                        applied_kg_as_fed_pen=ratio(applied_dm, dm_fraction),
                        applied_kg_as_fed_per_animal=ratio(ratio(applied_dm, dm_fraction), animals),
                        applied_usd=ingredient_cost,
                        applied_cost_share=ratio(ingredient_cost, cost),
                        inclusion_fraction=ratio(applied_dm, dm),
                        formula_inclusion_fraction=ratio(formulated_dm, formed_dm),
                    )
                )
            for row in nrc_balance(
                values["requirements"], values["supply"], values["legacy"], group, success, config, feed
            ):
                if success and success.get("traced_quantities_match_reported"):
                    residuals = success.get("trace_residuals") or {}
                    row["trace_margin"] = residuals.get(row["constraint"])
                balances.append(dict(base, **row))
        accumulate([row for row in pens if row["pen_id"] == pen], ("applied_usd", "milk_kg", "applied_dm_kg"))

    if not pen_keys:
        issues.append("Nenhum lote identificado nas séries de ração formulada.")
    daily = []
    for day, date in sorted(dates.items(), key=lambda item: item[1]):
        rows = [row for row in pens if row["simulation_day"] == day]
        cost = total(r["applied_usd"] for r in rows)
        animals = total(r["animals"] for r in rows)
        dm = total(r["applied_dm_kg"] for r in rows)
        milk = herd_milk.get(day, {}).get("value")
        herd_ingredients = ingredients(herd_feed.get(day, {}).get("value", {}))
        mix_by_feed = defaultdict(list)
        for row in mixes:
            if row["simulation_day"] == day:
                mix_by_feed[row["ingredient_id"]].append(row["applied_kg_dm_pen"])
        if herd_ingredients and any(
            not close(total(mix_by_feed[key]), amount) for key, amount in herd_ingredients.items()
        ):
            issues.append(f"Dia {day}: composição somada dos lotes diverge da série do rebanho.")
        values = {field: total(r[field] for r in rows) for field in ("reformulations", "attempts", "failures")}
        daily.append(
            dict(
                run=label,
                date=date,
                simulation_day=day,
                day_number=day + 1,
                **values,
                animals=animals,
                applied_dm_kg=dm,
                applied_usd=cost,
                milk_kg=milk,
                applied_usd_per_animal=ratio(cost, animals),
                usd_per_kg_milk=ratio(cost, milk),
                purchase_usd=total(r["purchase_usd"] for r in purchases if r["date"] == date),
                optimization_s=total(r["optimization_s"] for r in rows if r["attempts"]),
            )
        )
    accumulate(daily, ("applied_usd", "milk_kg", "applied_dm_kg", "purchase_usd"))
    if expected != set(dates.values()):
        for row in daily + pens:
            for key in row.keys():
                if key.startswith("cumulative_"):
                    row[key] = None
    animal_without_backend = dict(
        animal,
        ration={
            k: v
            for k, v in animal.get("ration", {}).items()
            if k != "optimizer_backend" and not k.startswith("linear_")
        },
    )
    return dict(
        run=label,
        daily=daily,
        pens=pens,
        composition=mixes,
        nutrition=balances,
        attempts=attempts,
        purchases=purchases,
        prices=prices,
        issues=list(dict.fromkeys(issues)),
        seed=seed,
        animal=animal_without_backend,
        ration_config=animal.get("ration", {}),
        config=config,
        hashes=hashes,
        source=str(source),
        source_sha256=digest(source),
        metadata=str(metadata),
        console=str(console) if console else None,
        reuse_log_count=reuse,
        trace=str(trace) if trace else None,
        complete_calendar=expected == set(dates.values()),
    )


def compare_runs(base, other, table):
    return compare_rows(base, other, table, ("date", "pen_id", "group") if table == "pens" else ("date",), METRICS)


def compare_rows(base, other, table, fields, metrics):
    left, right = ({tuple(row[field] for field in fields): row for row in run[table]} for run in (base, other))
    same_period = (
        left.keys() == right.keys() and base.get("complete_calendar", True) and other.get("complete_calendar", True)
    )
    rows = []
    for key in sorted(left.keys() | right.keys()):
        a, b = left.get(key, {}), right.get(key, {})
        row = dict(
            zip(fields, key, strict=True),
            baseline=base["run"],
            comparison=other["run"],
            baseline_present=bool(a),
            comparison_present=bool(b),
        )
        for field in metrics:
            x, y = a.get(field), b.get(field)
            delta = subtract(y, x) if same_period or not field.startswith("cumulative_") else None
            row.update(
                {
                    f"{field}_baseline": x,
                    f"{field}_comparison": y,
                    f"{field}_delta": delta,
                    f"{field}_delta_pct": ratio(delta * 100, x) if delta is not None else None,
                }
            )
        rows.append(row)
    return rows


def integrity(base, other):
    def check(a, b):
        return "indisponível" if a is None or b is None else "compatível" if a == b else "divergente"

    hashes = {
        key: check(base["hashes"].get(key), other["hashes"].get(key))
        for key in sorted(base["hashes"].keys() | other["hashes"].keys())
        if key != "animal"
    }
    return dict(
        baseline=base["run"],
        comparison=other["run"],
        dates=check([r["date"] for r in base["daily"]], [r["date"] for r in other["daily"]]),
        configuration=check(base["config"], other["config"]),
        animal_configuration=check(base["animal"], other["animal"]),
        seed=check(
            base["seed"][0] if len(base["seed"]) == 1 else None, other["seed"][0] if len(other["seed"]) == 1 else None
        ),
        prices=check(base["prices"], other["prices"]),
        inputs=hashes,
    )


def main():
    from .comparison_report_output import generate

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run",
        nargs=3,
        action="append",
        required=True,
        metavar=("LABEL", "JSON", "METADATA"),
        help="Repita para cada execução. Todos os pares são comparados na ordem informada.",
    )
    parser.add_argument(
        "--console",
        nargs=2,
        action="append",
        default=[],
        metavar=("LABEL", "LOG"),
        help="Log opcional da mesma execução, para verificar reaproveitamento.",
    )
    parser.add_argument(
        "--trace",
        nargs=2,
        action="append",
        default=[],
        metavar=("LABEL", "JSONL"),
        help="Rastreamento opcional de tentativas da mesma execução.",
    )
    parser.add_argument("--output", type=Path, required=True, help="Novo diretório de saída.")
    args = parser.parse_args()
    labels = [label for label, _, _ in args.run]
    consoles = dict(args.console)
    traces = dict(args.trace)
    if len(labels) < 2 or len(set(labels)) != len(labels) or not consoles.keys() | traces.keys() <= set(labels):
        parser.error(
            "Informe pelo menos dois rótulos distintos e associe arquivos auxiliares somente a execuções informadas."
        )
    if args.output.exists():
        parser.error("--output deve apontar para um novo diretório.")
    try:
        runs = [
            extract_run(
                label,
                Path(source),
                Path(metadata),
                Path(consoles[label]) if label in consoles else None,
                Path(traces[label]) if label in traces else None,
            )
            for label, source, metadata in args.run
        ]
        generate(runs, args.output)
    except (KeyError, ValueError, OSError) as error:
        parser.exit(1, f"Falha ao gerar relatório: {error}\n")
    print(args.output.resolve() / "index.html")


if __name__ == "__main__":
    main()
