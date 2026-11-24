"""Prepare and run the three-day NRC feeding experiment through the RuFaS CLI."""

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
BASE = Path("output/nrc_cli_three_day")
METHODS = {
    "slsqp": ("slsqp", "adaptive_gap"),
    "single": ("pulp", "single"),
    "full": ("pulp", "full"),
    "adaptive_gap": ("pulp", "adaptive_gap"),
}
SEED = 42
EXTRA_FEEDS = {167: 0.37, 231: 0.60}


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8-sig"))


def write(path, value):
    path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def default_scenario():
    """Construct the validated experimental inputs from versioned templates."""
    meta_template = read("input/metadata/example_animals_only_metadata.json")
    files = meta_template["files"]
    with (ROOT / files["NRC_Comp"]["path"]).open(newline="", encoding="utf-8-sig") as source:
        nrc = {int(row["rufas_id"]): row for row in csv.DictReader(source)}
    config = read(files["config"]["path"])
    config.update(start_date="2013:150", end_date="2013:152", nutrient_standard="NRC", set_seed=True)
    feed = read(files["feed"]["path"])
    excluded = [item["feed_type"] for item in feed["feeds"] if item["feed_type"] not in nrc]
    feed["feeds"] = [item for item in feed["feeds"] if item["feed_type"] in nrc]
    feed["feeds"].extend(
        {**feed["feeds"][0], "feed_type": feed_id, "purchased_feed_cost": price}
        for feed_id, price in EXTRA_FEEDS.items()
    )
    prices = {item["feed_type"]: item["purchased_feed_cost"] for item in feed["feeds"]}
    for recipe in feed["rations"]:
        ingredients = [item for item in recipe["feeds"] if item["feed_type"] in prices]
        if recipe["animal_combination"] != "calf":
            subtotal = sum(item["ration_percentage"] for item in ingredients)
            for ingredient in ingredients:
                ingredient["ration_percentage"] *= 100 / subtotal
            ingredients.extend({"feed_type": feed_id, "ration_percentage": 0} for feed_id in EXTRA_FEEDS)
        recipe["feeds"] = ingredients
    assert set(prices) <= nrc.keys()
    animal_template = read(files["animal"]["path"])
    assert {pen["animal_combination"].lower() for pen in animal_template["pen_information"]} == {
        recipe["animal_combination"] for recipe in feed["rations"]
    }
    for item in feed["feeds"]:
        nutrition = nrc[item["feed_type"]]
        assert nutrition["units"] == "kg" and float(nutrition["DM"]) > 0
        assert 0 <= float(nutrition["lower_limit"]) <= float(nutrition["limit"]) <= 100
    preflight = {
        "seed": SEED,
        "dates": [config["start_date"], config["end_date"]],
        "population": files["animal_population"]["path"],
        "excluded_feed_ids": excluded,
        "added_feed_prices": EXTRA_FEEDS,
        "nutritional_composition": {feed_id: nrc[feed_id] for feed_id in prices},
        "groups": {
            recipe["animal_combination"]: [item["feed_type"] for item in recipe["feeds"]] for recipe in feed["rations"]
        },
    }
    return meta_template, config, feed, preflight


def write_json_filter(base):
    filters = ROOT / base / "filters"
    filters.mkdir(parents=True, exist_ok=True)
    (filters / "json_cli_feeding.txt").write_text(".*\n", encoding="utf-8")


def write_task_inputs(inputs, metadata, filters, output, name, seed, verbosity):
    """Write a single-run task and its manager using the checked-in templates."""
    write(inputs / "metadata.json", metadata)
    task = read("input/data/tasks/example_animals_only_task.json")
    task["parallel_workers"] = 1
    task["tasks"][0].update(
        metadata_file_path=(inputs / "metadata.json").as_posix(),
        filters_directory=filters.as_posix(),
        output_prefix=name,
        log_verbosity=verbosity,
        random_seeds=[seed],
        json_output_directory=(output / "JSONs").as_posix(),
        csv_output_directory=(output / "CSVs").as_posix(),
        logs_directory=(output / "logs").as_posix(),
        report_directory=(output / "reports").as_posix(),
        graphics_directory=(output / "graphics").as_posix(),
        save_animals_directory=(output / "animals").as_posix(),
    )
    write(inputs / "task.json", task)
    task_manager = read("input/task_manager_metadata.json")
    task_manager["files"]["tasks"]["path"] = (inputs / "task.json").as_posix()
    write(inputs / "task_manager.json", task_manager)
    return inputs / "task_manager.json"


def prepare(base):
    metadata, config, feed, preflight = default_scenario()
    files = metadata["files"]
    write(base / "inputs/config.json", config)
    write(base / "inputs/feed.json", feed)
    write(base / "inputs/preflight.json", preflight)
    write_json_filter(base)
    for name, (backend, strategy) in METHODS.items():
        inputs = base / "inputs" / name
        animal = read(files["animal"]["path"])
        animal["ration"].update(
            user_input=False,
            formulation_interval=1,
            optimizer_backend=backend,
            linear_strategy=strategy,
            linear_gap_target=0.05,
            linear_max_references=5,
        )
        write(inputs / "animal.json", animal)
        metadata = read("input/metadata/example_animals_only_metadata.json")
        for key, path in {
            "animal": inputs / "animal.json",
            "feed": base / "inputs/feed.json",
            "config": base / "inputs/config.json",
        }.items():
            metadata["files"][key]["path"] = path.as_posix()
        write_task_inputs(inputs, metadata, base / "filters", base / "runs" / name, name, SEED, "logs")


def run(base, name):
    output = base / "runs" / name
    (ROOT / output).mkdir(parents=True, exist_ok=False)
    command = [
        sys.executable,
        "main.py",
        "-g",
        "-v",
        "logs",
        "-p",
        (base / "inputs" / name / "task_manager.json").as_posix(),
        "-o",
        output.as_posix(),
        "-l",
        (output / "logs").as_posix(),
    ]
    started = perf_counter()
    with (ROOT / output / "console.log").open("w", encoding="utf-8") as console:
        result = subprocess.run(command, cwd=ROOT, stdout=console, stderr=subprocess.STDOUT, check=False)
    seconds = perf_counter() - started
    logs = (ROOT / output).rglob("*.log")
    completed = any("Simulation completed" in path.read_text(encoding="utf-8", errors="replace") for path in logs)
    write(
        output / "run.json",
        {
            "command": command,
            "wall_seconds": seconds,
            "exit_code": result.returncode,
            "simulation_completed": completed,
        },
    )
    print(f"{name}: code={result.returncode}, completed={completed}, wall={seconds:.3f} s", flush=True)
    return result.returncode == 0 and completed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=BASE)
    parser.add_argument("action", choices=("prepare", *METHODS))
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.base)
    elif not run(args.base, args.action):
        sys.exit(1)


if __name__ == "__main__":
    main()
