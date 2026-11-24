"""Write the HTML, CSV and PNG artifacts for a comparison."""

import base64
import csv
import html
import json
import math
from collections import Counter, defaultdict
from itertools import combinations
from statistics import median

from .comparison_report import compare_rows, compare_runs, integrity, ratio, total
from .comparison_report_summary import render


def flatten(value):
    return json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list, tuple)) else value


def csv_write(path, rows, columns=()):
    fields = list(dict.fromkeys((*columns, *(key for row in rows for key in row))))
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        writer.writerows({k: flatten(v) for k, v in row.items()} for row in rows)


def executive(run):
    final = run["daily"][-1]
    lac = [row for row in run["attempts"] if row["animal_group"] == "lac_cow"]
    gaps = [row["gap_percent"] for row in lac if row.get("gap_percent") is not None and row["success"]]
    return {
        "Execução": run["run"],
        "Dias": len(run["daily"]),
        "Custo fornecido (US$)": final["cumulative_applied_usd"],
        "MS fornecida (kg)": final["cumulative_applied_dm_kg"],
        "Leite (kg)": final["cumulative_milk_kg"],
        "US$/kg de leite": ratio(final["cumulative_applied_usd"], final["cumulative_milk_kg"]),
        "Aquisição observada (US$)": total(row["purchase_usd"] for row in run["purchases"]),
        "Tentativas (lactação)": len(lac) if run["attempts"] else None,
        "Sucessos registrados (lactação)": sum(r["success"] is True for r in lac) if run["attempts"] else None,
        "Aprovações NRC lineares (lactação)": total(
            int(r["linear_nrc_approved"]) for r in lac if r["linear_nrc_approved"] is not None
        ),
        "Falhas registradas (todos os lotes)": (
            sum(r["success"] is False for r in run["attempts"]) if run["attempts"] else None
        ),
        "Tentativas adicionais (todos os lotes)": (
            sum(r["attempt"] > 1 for r in run["attempts"]) if run["attempts"] else None
        ),
        "Reaproveitamentos (log)": run["reuse_log_count"],
        "Otimização lactação (s)": total(r.get("optimization_seconds") for r in lac),
        "Gap mediano (%)": median(gaps) if gaps else None,
    }


def ingredient_totals(run):
    costs = defaultdict(list)
    names = {}
    for row in run["composition"]:
        key = row["ingredient_id"]
        costs[key].append(row["applied_usd"])
        names[key] = row["name"]
    denominator = run["daily"][-1]["cumulative_applied_usd"]
    return [
        dict(
            run=run["run"],
            ingredient_id=key,
            name=names[key],
            applied_usd=total(values),
            share=ratio(total(values), denominator),
        )
        for key, values in sorted(costs.items(), key=lambda item: int(item[0]))
    ]


def graph(path, title, ylabel, draw, dates=False):
    from matplotlib import dates as mdates
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    fig = Figure(figsize=(10.5, 4.7), layout="constrained")
    FigureCanvasAgg(fig)
    ax = fig.subplots()
    draw(ax)
    ax.set(title=title, ylabel=ylabel)
    ax.spines[["right", "top"]].set_visible(False)
    ax.grid(axis="y", alpha=0.23)
    if dates:
        locator = mdates.AutoDateLocator(minticks=3, maxticks=10)
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(handles, labels, fontsize=8, loc="best", ncols=2, frameon=False)
    if not ax.has_data():
        ax.text(0.5, 0.5, "Dados indisponíveis", transform=ax.transAxes, ha="center", va="center")
    fig.savefig(path, dpi=220)


def plots(runs, destination, shares):
    from matplotlib import dates as mdates

    def line(ax, table, field, lactation=False):
        for run in runs:
            rows = [r for r in run[table] if not lactation or r["group"] == "LAC_COW"]
            by_date = defaultdict(list)
            for row in rows:
                by_date[row["date"]].append(row.get(field))
            values = {
                date: (sum(items) / len(items) if all(item is not None for item in items) else math.nan)
                for date, items in sorted(by_date.items())
            }
            if any(math.isfinite(value) for value in values.values()):
                ax.plot(
                    [mdates.datestr2num(date) for date in values],
                    list(values.values()),
                    marker="o",
                    markersize=3,
                    linewidth=1.5,
                    label=run["run"],
                )

    files = []

    def add(filename, title, unit, draw, dates=False):
        name = filename + ".png"
        graph(destination / name, title, unit, draw, dates)
        files.append((name, title))

    for filename, title, unit, table, field, lac in (
        (
            "cost_per_animal",
            "Custo diário médio por animal do rebanho",
            "US$/animal/dia",
            "daily",
            "applied_usd_per_animal",
            False,
        ),
        ("daily_cost", "Custo diário da alimentação fornecida", "US$/dia", "daily", "applied_usd", False),
        (
            "cumulative_cost",
            "Custo acumulado da alimentação fornecida",
            "US$",
            "daily",
            "cumulative_applied_usd",
            False,
        ),
        ("milk", "Produção diária de leite do rebanho", "kg/dia", "daily", "milk_kg", False),
        ("cost_per_kg_milk", "Custo alimentar do rebanho por kg de leite", "US$/kg", "daily", "usd_per_kg_milk", False),
        ("optimization_time", "Tempo diário de otimização dos lotes", "segundos", "daily", "optimization_s", False),
        ("gap", "Gap econômico das tentativas com sucesso na lactação", "%", "pens", "gap_percent", True),
    ):
        add(filename, title, unit, lambda ax: line(ax, table, field, lac), True)

    def bars(ax, rows, xlabel, ylabel):
        categories = list(dict.fromkeys(row[0] for row in rows))
        width = 0.8 / len(runs)
        for i, run in enumerate(runs):
            values = {category: value for category, label, value in rows if label == run["run"] and value is not None}
            positions = [
                j + (i - (len(runs) - 1) / 2) * width for j, category in enumerate(categories) if category in values
            ]
            if positions:
                ax.bar(
                    positions,
                    [values[category] for category in categories if category in values],
                    width,
                    label=run["run"],
                )
        ax.set_xticks(range(len(categories)), categories, rotation=25, ha="right")
        ax.set(xlabel=xlabel, ylabel=ylabel)

    share_points = [(r["ingredient_id"], r["run"], r["share"] * 100) for r in shares if r["share"] is not None]
    add(
        "ingredient_cost_share",
        "Participação no custo acumulado do rebanho",
        "%",
        lambda ax: bars(ax, share_points, "ID do ingrediente", "%"),
    )

    winners = [
        (ref, run["run"], count)
        for run in runs
        for ref, count in Counter(
            r["reference"] for r in run["attempts"] if r["success"] and r.get("reference")
        ).items()
    ]
    add(
        "references",
        "Frequência das referências vencedoras",
        "tentativas",
        lambda ax: bars(ax, winners, "Referência", "tentativas"),
    )

    nutrition_points = []
    for run in runs:
        by_constraint = defaultdict(list)
        for row in run["nutrition"]:
            if row["group"] == "LAC_COW" and row["audit_status"]:
                by_constraint[row["constraint"]].append(row["audit_status"] == "atende")
        nutrition_points.extend(
            (key.replace("_constraint", ""), run["run"], sum(passes) / len(passes) * 100)
            for key, passes in by_constraint.items()
        )
    add(
        "nutrition",
        "Atendimento das restrições NRC na lactação, auditoria da dieta reportada",
        "%",
        lambda ax: bars(ax, nutrition_points, "Restrição", "% de observações avaliáveis"),
    )

    def stack(ax, rows):
        by_ingredient = defaultdict(dict)
        for row in rows:
            if row["applied_kg_dm_per_animal"] is not None:
                by_ingredient[row["ingredient_id"]][row["date"]] = row["applied_kg_dm_per_animal"]
        dates = sorted({row["date"] for row in rows})
        bottoms = [0.0] * len(dates)
        for key, values in by_ingredient.items():
            heights = [values.get(date, 0) for date in dates]
            if any(heights):
                ax.bar([mdates.datestr2num(date) for date in dates], heights, bottom=bottoms, label=key)
                bottoms = [a + b for a, b in zip(bottoms, heights, strict=True)]

    for index, run in enumerate(runs, 1):
        for pen, group in sorted({(r["pen_id"], r["group"]) for r in run["composition"]}):
            rows = [r for r in run["composition"] if r["pen_id"] == pen and r["group"] == group]
            add(
                f"composition_{index}_pen_{pen}",
                f'{run["run"]} · lote {pen} ({group}) · ingredientes por ID',
                "kg MS fornecida/animal",
                lambda ax: stack(ax, rows),
                True,
            )
    return files


def cell(value):
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Sim" if value else "Não"
    if isinstance(value, float):
        return f"{value:.9g}"
    return html.escape(str(flatten(value)))


def table(rows, columns=None):
    if not rows:
        return "<p>Dados indisponíveis.</p>"
    columns = columns or list(dict.fromkeys(key for row in rows for key in row))
    head = "".join(f"<th scope='col'>{cell(key)}</th>" for key in columns)
    body = "".join("<tr>" + "".join(f"<td>{cell(row.get(key))}</td>" for key in columns) + "</tr>" for row in rows)
    return f"<div class='table'><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def details(title, body, opened=False):
    return f"<details{' open' if opened else ''}><summary>{cell(title)}</summary>{body}</details>"


NOTES = (
    "Custos fornecidos = kg de MS informados por lote × preços de entrada da otimização em US$/kg MS. "
    "O custo formulado usa os kg por animal da ração registrada. O custo por kg de leite do rebanho inclui todos os lotes. "
    "Aquisições usam os lançamentos de FeedManager.purchase_feed quando disponíveis. O acumulado de aquisições observadas "
    "soma lançamentos exportados. Dias sem lançamentos assinalam cobertura desconhecida no CSV diário.",
    "Matéria natural por ingrediente usa kg MS ÷ fração de MS do cadastro de composição. "
    "As contagens na formulação e no fornecimento vêm de eventos distintos. O leite por lote é agregado por ID da vaca "
    "e pela baia no registro individual. O leite total usa a série oficial do rebanho.",
    "As colunas de auditoria nutricional usam oferta e meta publicadas e limites NRC da revisão local. "
    "São calculadas quando a tentativa com sucesso é a primeira do dia e o contexto é identificável. "
    "A margem é oferta menos mínimo ou máximo menos oferta. A tolerância é a da checagem linear, aplicada aqui como "
    "critério de auditoria descritivo, inclusive nas dietas SLSQP. Cálcio e fósforo são digestíveis e foram convertidos "
    "de kg para g. O fósforo exigido usa o maior valor entre o balanço nutricional e o balanço de processos.",
    "No AnimalModuleReporter, zero para DMI, proteína metabolizável e FDN pode representar uma oferta dentro da faixa. "
    "O indicador do reporter para MP ou DMI pode usar limites diferentes dos efetivos em uma reformulação. O campo legacy_evaluator "
    "descreve a avaliação registrada pelo fluxo SLSQP. A aprovação NRC linear vem do registro da tentativa PuLP. "
    "O sucesso registrado para PuLP é o resultado do adaptador. O status do LP vencedor e os resíduos da dieta aplicada vêm do rastreamento quando a composição coincide. "
    "Para SLSQP, a coluna slsqp_posthoc_nrc_pass descreve a checagem externa feita pela instrumentação.",
    "Diferenças são comparação menos base. Percentuais usam o valor da base e ficam vazios se ele for zero ou desconhecido. "
    "As linhas são alinhadas por data civil e, para lotes, por ID e grupo. A soma acumulada é exibida quando a cobertura "
    "permite. Diferenças em trajetórias biológicas ou na composição do rebanho limitam a interpretação causal.",
    "Tempos de otimização incluem a instrumentação ativa em cada execução. Compare os tempos qualitativamente quando a instrumentação diferir. "
    "Uma referência previous_ration pode vencer uma formulação nova e é registrada separadamente de reaproveitamento após falha.",
    "Os hashes de configuração vêm dos arquivos fornecidos ao relatório. A identidade entre esses arquivos e os usados "
    "no momento da execução depende da proveniência dos insumos. Marcas de reaproveitamento dependem do log correto.",
)


def generate(runs, destination, *, html=True):
    destination.mkdir(parents=True, exist_ok=False)
    herd = [row for run in runs for row in run["daily"]]
    pens = [row for run in runs for row in run["pens"]]
    mixes = [row for run in runs for row in run["composition"]]
    nutrition = [row for run in runs for row in run["nutrition"]]
    attempts = [row for run in runs for row in run["attempts"]]
    purchases = [row for run in runs for row in run["purchases"]]
    shares = [row for run in runs for row in ingredient_totals(run)]
    checks, herd_delta, pen_delta, ingredient_delta = [], [], [], []
    for base, other in combinations(runs, 2):
        checks.append(integrity(base, other))
        herd_delta.extend(compare_runs(base, other, "daily"))
        pen_delta.extend(compare_runs(base, other, "pens"))
        ingredient_delta.extend(
            compare_rows(
                base,
                other,
                "composition",
                ("date", "pen_id", "group", "ingredient_id"),
                ("applied_usd", "applied_cost_share", "applied_kg_dm_per_animal", "formulated_usd_per_animal"),
            )
        )
    summary = [executive(run) for run in runs]
    last_delta = {(row["baseline"], row["comparison"]): row for row in herd_delta}
    final_deltas = [
        {
            key: row[key]
            for key in (
                "baseline",
                "comparison",
                "date",
                "cumulative_applied_usd_delta",
                "cumulative_applied_usd_delta_pct",
                "cumulative_milk_kg_delta",
                "cumulative_milk_kg_delta_pct",
                "cumulative_applied_dm_kg_delta",
                "cumulative_applied_dm_kg_delta_pct",
            )
        }
        for row in last_delta.values()
    ]
    csv_files = []
    for name, rows, columns in (
        ("summary", summary, ()),
        ("daily_herd", herd, ()),
        ("daily_pens", pens, ()),
        ("composition", mixes, ()),
        ("ingredient_costs", shares, ()),
        ("nutrition", nutrition, ()),
        ("attempts", attempts, ()),
        (
            "purchases",
            purchases,
            ("run", "simulation_day", "date", "purchase_type", "ingredient_id", "purchase_usd", "reported_unit"),
        ),
        ("herd_deltas", herd_delta, ()),
        ("pen_deltas", pen_delta, ()),
        ("ingredient_deltas", ingredient_delta, ()),
        ("integrity", checks, ()),
    ):
        csv_files.append(name + ".csv")
        csv_write(destination / csv_files[-1], rows, columns)
    provenance = [
        {
            k: run[k]
            for k in (
                "run",
                "source",
                "source_sha256",
                "metadata",
                "console",
                "config",
                "seed",
                "ration_config",
                "hashes",
                "prices",
                "issues",
                "trace",
            )
        }
        for run in runs
    ]
    (destination / "provenance.json").write_text(
        json.dumps(provenance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    if not html:
        return

    figures = {}
    for name, title in plots(runs, destination, shares):
        encoded = base64.b64encode((destination / name).read_bytes()).decode("ascii")
        figures[name] = (
            title,
            f"<figure><img loading='lazy' src='data:image/png;base64,{encoded}' alt='{cell(title)}'></figure>",
        )
    first = [r for r in nutrition if r["group"] == "LAC_COW" and r["simulation_day"] == 0]
    columns = (
        "run",
        "pen_id",
        "constraint",
        "unit_per_animal_day",
        "nutritional_target",
        "effective_limit",
        "offer",
        "offer_minus_target",
        "margin",
        "audit_tolerance",
        "audit_status",
        "reporter_evaluation",
        "trace_margin",
    )
    issues = "".join(
        f"<h3>{cell(run['run'])}</h3><ul>" + "".join(f"<li>{cell(issue)}</li>" for issue in run["issues"]) + "</ul>"
        for run in runs
    )
    changed_production = any(row["milk_kg_delta"] not in (None, 0) for row in herd_delta)
    changed_targets = any(
        len(
            {
                r["nutritional_target"]
                for r in nutrition
                if r["date"] == day and r["group"] == "LAC_COW" and r["constraint"] == "DMI_constraint_lower"
            }
        )
        > 1
        for day in {r["date"] for r in herd}
    )
    biological = (
        "Há diferenças observadas nas trajetórias de produção de leite ou nas metas estimadas de DMI. "
        "Os totais são descritivos e não identificam o efeito causal do backend."
        if changed_production or changed_targets
        else "Os totais sintetizam as trajetórias observadas sob as entradas documentadas."
    )
    examples = [r for r in attempts if r["animal_group"] == "lac_cow" and r["simulation_day"] in {7, 8, 14, 15}]
    sections = (
        (
            "Resumo executivo",
            f"<p>{cell(biological)}</p>"
            + table(summary)
            + details("Diferenças acumuladas", table(final_deltas), True)
            + details("Integridade entre execuções", table(checks)),
        ),
        (
            "Comparação diária",
            details("Rebanho", table(herd), True)
            + details("Lotes", table(pens))
            + details("Diferenças por rebanho", table(herd_delta))
            + details("Diferenças por lote", table(pen_delta)),
        ),
        (
            "Composição e custos",
            details("Custo por ingrediente no período", table(shares), True)
            + details("Ingredientes por dia e lote", table(mixes))
            + details("Diferenças diárias por ingrediente e lote", table(ingredient_delta))
            + details("Aquisições registradas", table(purchases)),
        ),
        (
            "Balanço nutricional",
            details("Primeira dieta de lactação em cada execução", table(first, columns), True)
            + details("Todas as dietas e restrições", table(nutrition)),
        ),
        (
            "Diagnósticos",
            details(
                "Dias 8 e 15 nas duas convenções de numeração",
                table(
                    examples,
                    (
                        "run",
                        "simulation_day",
                        "date",
                        "pen_id",
                        "attempt",
                        "backend",
                        "success",
                        "nutritional_validation",
                        "reference",
                    ),
                ),
                True,
            )
            + details("Tentativas e referências regionais", table(attempts)),
        ),
        ("Gráficos", "".join(markup for _, markup in figures.values())),
        (
            "Limitações e proveniência",
            "".join(f"<p>{cell(note)}</p>" for note in NOTES)
            + issues
            + details("Arquivos de origem e configuração", table(provenance)),
        ),
    )
    nav = " · ".join(f"<a href='#s{i}'>{cell(title)}</a>" for i, (title, _) in enumerate(sections))
    content = "".join(
        f"<section id='s{i}'><h2>{cell(title)}</h2>{body}</section>" for i, (title, body) in enumerate(sections)
    )
    head = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport"
content="width=device-width, initial-scale=1"><title>Comparação de formulações RuFaS</title><style>
body{font:16px/1.55 system-ui,sans-serif;color:#162629;background:#f8faf9;margin:0}
main{max-width:1250px;margin:auto;padding:clamp(1rem,4vw,3rem)}h1{font-size:clamp(2rem,5vw,3.5rem);margin:0}
nav{margin:1rem 0 2rem}a{color:#12604e}section{margin:2.5rem 0}details{margin:.7rem 0;background:white;border:1px solid #cdd9d5}
summary{padding:.65rem;cursor:pointer;font-weight:650}.table{overflow:auto;max-height:34em}
table{border-collapse:collapse;width:100%;font-size:.85rem}th,td{text-align:left;border-bottom:1px solid #dae3e0;padding:.4rem .65rem}
th{background:#dfeee8;position:sticky;top:0}td{max-width:28em;overflow-wrap:anywhere}tr:nth-child(even){background:#f1f6f4}
figure{margin:1.5rem 0;background:white}img{display:block;width:min(100%,1000px);margin:auto;height:auto}
</style></head><body><main><h1>Comparação de formulações RuFaS</h1>"""
    back = '<p><a href="index.html">Voltar ao relatório resumido</a></p>'
    (destination / "detailed_report.html").write_text(
        head + back + f"<nav>{nav}</nav>{content}</main></body></html>", encoding="utf-8"
    )
    (destination / "index.html").write_text(
        render(runs, summary, final_deltas, biological, figures, csv_files, cell, table, details), encoding="utf-8"
    )
