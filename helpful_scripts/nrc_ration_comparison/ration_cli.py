"""Launch reproducible experimental ration simulations with the original RuFaS CLI."""

import argparse
import datetime as dt
import subprocess
import sys
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from .cli_three_day import ROOT, SEED, default_scenario, read, write, write_json_filter, write_task_inputs

DEFAULT_REFERENCES = 5
MIDWEST = "input/data/feed/example_Midwest_feed.json"
FINISHED = "TaskManager.handle_single_simulation_run.Simulation completed"


@dataclass(frozen=True)
class Method:
    label: str
    references: int | None = None

    @property
    def backend(self):
        return "slsqp" if self.references is None else "pulp"


@dataclass(frozen=True)
class PreparedRun:
    method: Method
    task_manager: Path
    metadata: Path
    output: Path


def positive_int(value):
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("informe um inteiro positivo")
    return parsed


def seed_int(value):
    parsed = positive_int(value)
    if parsed >= 2**32:
        raise argparse.ArgumentTypeError("a semente deve estar entre 1 e 4294967295")
    return parsed


def gap_fraction(value):
    parsed = float(value)
    if not 0 <= parsed < 1:
        raise argparse.ArgumentTypeError("informe uma fração de 0 até menos de 1, por exemplo 0.05")
    return parsed


def parse_args(compare_mode, argv=None):
    command = "rufas-compare" if compare_mode else "rufas-linear"
    parser = argparse.ArgumentParser(
        prog=command, description="Executa o cenário experimental de alimentação do RuFaS."
    )
    parser.add_argument("--days", type=positive_int, default=3, help="dias corridos de simulação (padrão: 3)")
    parser.add_argument("--seed", type=seed_int, default=SEED, help="semente fixa (padrão: 42)")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "output/ration_cli",
        help="pasta pai onde será criado um diretório exclusivo",
    )
    parser.add_argument("--config", type=Path, help="JSON de configuração base da simulação")
    parser.add_argument("--metadata", type=Path, help="JSON de metadados da simulação")
    parser.add_argument("--strategy", choices=("single", "full", "adaptive_gap"), default="full")
    parser.add_argument("--gap-target", type=gap_fraction, default=0.05, help="fração de gap para adaptive_gap")
    parser.add_argument("--midwest", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--verbosity", choices=("none", "credits", "errors", "warnings", "logs"), default="none")
    parser.add_argument("--html", action="store_true", help="gera também os dois relatórios HTML e os gráficos")
    parser.add_argument(
        "--references",
        type=positive_int,
        nargs="+" if compare_mode else None,
        default=[DEFAULT_REFERENCES] if compare_mode else DEFAULT_REFERENCES,
        help="orçamento de referências por execução HiGHS (padrão: 5)",
    )
    if compare_mode:
        parser.add_argument(
            "--methods",
            nargs="+",
            choices=("slsqp", "highs"),
            default=["slsqp", "highs"],
            help="métodos executados na ordem indicada; highs aceita vários orçamentos",
        )
    args = parser.parse_args(argv)
    if compare_mode:
        if len(set(args.methods)) != len(args.methods) or len(set(args.references)) != len(args.references):
            parser.error("informe métodos e orçamentos distintos")
        args.methods = [
            method
            for name in args.methods
            for method in ([Method("slsqp")] if name == "slsqp" else [Method(f"highs{n}", n) for n in args.references])
        ]
    else:
        args.methods = [Method(f"highs{args.references}", args.references)]
    return args


def allocate_output(parent, command):
    parent = parent.resolve()
    parent.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = parent / f"{command}-{stamp}-{uuid4().hex[:12]}"
    path.mkdir(exist_ok=False)
    return path


def simulation_dates(config):
    year, day = map(int, config["start_date"].split(":"))
    start = dt.date(year, 1, 1) + dt.timedelta(days=day - 1)
    if day < 1 or start.year != year:
        raise ValueError("start_date deve ser um dia válido no formato ano:dia juliano")
    return start


def prepare(batch, args):
    if args.metadata is None:
        metadata, config, feed, _ = default_scenario()
    else:
        metadata = read(args.metadata.resolve())
        config = read(metadata["files"]["config"]["path"])
        feed = read(metadata["files"]["feed"]["path"])
    if args.config is not None:
        config = read(args.config.resolve())
    animal = read(metadata["files"]["animal"]["path"])
    has_linear = any(method.references is not None for method in args.methods)
    if config.get("simulation_type") not in {"animals_only", "full_farm"}:
        raise ValueError("o cenário precisa incluir o módulo animal (animals_only ou full_farm)")
    if args.metadata is None:
        animal["ration"].update(user_input=False, formulation_interval=1)
    if has_linear and (config.get("nutrient_standard") != "NRC" or animal["ration"].get("user_input")):
        raise ValueError("PuLP/HiGHS exige padrão NRC e formulação automática para o lote em lactação")
    start = simulation_dates(config)
    end = start + dt.timedelta(days=args.days - 1)
    config.update(end_date=f"{end.year}:{end.timetuple().tm_yday}", set_seed=True)

    common = batch / "inputs"
    write(common / "config.json", config)
    write(common / "feed.json", feed)
    write_json_filter(batch)
    metadata["files"]["config"]["path"] = (common / "config.json").as_posix()
    metadata["files"]["feed"]["path"] = (common / "feed.json").as_posix()
    runs = []
    for method in args.methods:
        arm_metadata = deepcopy(metadata)
        arm_animal = deepcopy(animal)
        ration = arm_animal["ration"]
        ration.update(optimizer_backend=method.backend)
        if method.references is not None:
            ration.update(
                linear_strategy=args.strategy,
                linear_gap_target=args.gap_target,
                linear_max_references=method.references,
                linear_reference_solver="highs",
                linear_bound_solver="highs",
                linear_nutritional_solver="highs",
                linear_midwest_reference_path=MIDWEST if args.midwest else "",
            )
        inputs = common / method.label
        output = batch / "runs" / method.label
        write(inputs / "animal.json", arm_animal)
        arm_metadata["files"]["animal"]["path"] = (inputs / "animal.json").as_posix()
        manager = write_task_inputs(
            inputs, arm_metadata, batch / "filters", output, method.label, args.seed, args.verbosity
        )
        runs.append(PreparedRun(method, manager, inputs / "metadata.json", output))
    dates = [(start + dt.timedelta(days=i)).isoformat() for i in range(args.days)]
    return runs, dates


def result_file(output, exit_code):
    if exit_code != 0:
        raise RuntimeError(f"RuFaS retornou código {exit_code}")
    logs = [read(path) for path in (output / "logs").glob("*_logs_*.json")]
    if not any("Simulation completed" in log.get(FINISHED, {}).get("values", []) for log in logs):
        raise RuntimeError("RuFaS não registrou a conclusão da simulação")
    files = sorted((output / "JSONs").glob("*_saved_variables_json_cli_feeding.txt_*.json"))
    if len(files) != 1:
        raise RuntimeError(f"esperava um JSON final do filtro de alimentação, encontrados {len(files)}")
    return files[0]


def check_result(run, method, dates, seed):
    if [day["date"] for day in run["daily"]] != dates or not run["complete_calendar"]:
        raise RuntimeError("o calendário do JSON final diverge do período solicitado")
    if run["seed"] != [seed]:
        raise RuntimeError("a semente registrada diverge da semente solicitada")
    if not run["pens"] or any(day[field] is None for day in run["daily"] for field in ("milk_kg", "applied_dm_kg")):
        raise RuntimeError("o JSON final não contém séries diárias completas de alimentação e leite")
    lactation = [row for row in run["attempts"] if row["animal_group"] == "lac_cow"]
    if not lactation or any(row["backend"] != method.backend for row in lactation):
        raise RuntimeError("o backend solicitado não foi confirmado no lote em lactação")
    if method.references is not None and any(
        row.get(f"{phase}_solver") != "HiGHS" for row in lactation for phase in ("reference", "bound", "nutritional")
    ):
        raise RuntimeError("HiGHS não foi confirmado nas três etapas da formulação linear")


def execute(prepared, args, dates):
    from .comparison_report import extract_run

    output = prepared.output
    output.mkdir(parents=True, exist_ok=False)
    console_path = output / "console.log"
    command = [
        sys.executable,
        "-B",
        "-m",
        "RUFAS.main",
        "--no-graphics",
        "--verbosity",
        args.verbosity,
        "--path-to-metadata",
        str(prepared.task_manager),
        "--output-dir",
        str(output),
        "--logs-dir",
        str(output / "logs"),
    ]
    status = {"command": command, "completed": False}
    start = perf_counter()
    try:
        with console_path.open("w", encoding="utf-8") as console:
            process = subprocess.run(command, cwd=ROOT, stdout=console, stderr=subprocess.STDOUT, check=False)
        status["wall_seconds"] = perf_counter() - start
        status["exit_code"] = process.returncode
        if args.verbosity != "none":
            print(console_path.read_text(encoding="utf-8", errors="replace").rstrip())
        source = result_file(output, process.returncode)
        status["result"] = str(source)
        run = extract_run(prepared.method.label, source, prepared.metadata, console_path)
        check_result(run, prepared.method, dates, args.seed)
        status["completed"] = True
        return run, status["wall_seconds"]
    except (KeyError, OSError, TypeError, ValueError, RuntimeError) as error:
        status["error"] = str(error)
        raise RuntimeError(f"{prepared.method.label}: {error}. Consulte {console_path}") from error
    finally:
        write(output / "run.json", status)


def run_cli(compare_mode, argv=None):
    args = parse_args(compare_mode, argv)
    try:
        if any(method.references is not None for method in args.methods):
            import pulp

            if not pulp.HiGHS(msg=False).available():
                raise ImportError("HiGHS indisponível")
    except ImportError as error:
        print(f"{error}. Instale o extra com python -m pip install -e '.[linear_ration_highs]'.", file=sys.stderr)
        return 1

    batch = None
    try:
        batch = allocate_output(args.output, "compare" if compare_mode else "linear")
        prepared, dates = prepare(batch, args)
        print(f"Cenário experimental · {dates[0]} a {dates[-1]} · semente {args.seed}", flush=True)
        print(f"Resultados em {batch}", flush=True)
        runs, walls, failures = [], {}, []
        for item in prepared:
            print(f"Executando {item.method.label}...", flush=True)
            try:
                run, seconds = execute(item, args, dates)
            except RuntimeError as error:
                failures.append(str(error))
                print(str(error), file=sys.stderr, flush=True)
            else:
                runs.append(run)
                walls[run["run"]] = seconds
        write(
            batch / "batch.json",
            {
                "requested": [item.method.label for item in prepared],
                "completed": list(walls),
                "failures": failures,
                "seed": args.seed,
                "dates": dates,
            },
        )
        if runs:
            from .comparison_report_output import generate
            from .terminal_report import summarize, show

            summary = summarize(runs, walls)
            write(batch / "terminal_summary.json", summary)
            show(summary)
            generate(runs, batch / "report", html=args.html)
            if args.html:
                print(f"\nHTML: {batch / 'report/index.html'}")
        return int(bool(failures))
    except (KeyError, OSError, OverflowError, TypeError, ValueError, RuntimeError) as error:
        print(f"Falha na CLI experimental: {error}", file=sys.stderr)
        if batch:
            print(f"Artefatos disponíveis em {batch}", file=sys.stderr)
        return 1


def linear():
    return run_cli(False)


def compare():
    return run_cli(True)
