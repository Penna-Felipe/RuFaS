import concurrent.futures
import shutil
from pathlib import Path
import hashlib
import subprocess
from helpful_scripts.nrc_ration_comparison import cli_solver_consolidation as cli

root = Path("output/nrc_midwest_30day")
root.mkdir(exist_ok=False)
(root / "inputs").mkdir()
for filename in ("feed.json", "preflight.json"):
    shutil.copyfile(cli.BASE / "inputs" / filename, root / "inputs" / filename)
config = cli.read(cli.BASE / "inputs/config.json")
config["end_date"] = "2013:179"
cli.write(root / "inputs/config.json", config)
shutil.copytree(cli.BASE / "filters", root / "filters")
cli.CONFIGURATIONS.update({
    "highs_midwest_3": ("full", ("highs", "highs", "highs")),
    "highs_midwest_5": ("full", ("highs", "highs", "highs")),
})
metadata = cli.read(cli.BASE / "inputs/full/metadata.json")
cli.write(root / "manifest.json", {
    "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    "diff_sha256": hashlib.sha256(subprocess.check_output(["git", "diff", "HEAD"])).hexdigest(),
    "start_date": config["start_date"], "end_date": config["end_date"], "seed": 42,
    "concurrent_processes": 3, "repetitions_per_configuration": 1,
    "source_checksums": {k: hashlib.sha256(Path(v["path"]).read_bytes()).hexdigest() for k,v in metadata["files"].items()},
})
runs = {}
for name in ("slsqp", "highs_midwest_3", "highs_midwest_5"):
    output, task = cli.prepare(root, name, 1)
    if name != "slsqp":
        path = root / "inputs" / name / "1/animal.json"
        animal = cli.read(path)
        animal["ration"]["linear_max_references"] = int(name[-1])
        animal["ration"]["linear_midwest_reference_path"] = "input/data/feed/example_Midwest_feed.json"
        cli.write(path, animal)
    runs[name] = output, task
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    futures = {pool.submit(cli.run, *args): name for name,args in runs.items()}
    for future in concurrent.futures.as_completed(futures):
        try:
            seconds = future.result()
            print(futures[future], "completed", round(seconds,3), flush=True)
        except Exception as error:
            print(futures[future], type(error).__name__, str(error), flush=True)
