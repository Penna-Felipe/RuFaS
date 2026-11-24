"""Render the compact, offline view of the comparative report."""

import datetime as dt
import json
from collections import Counter, defaultdict

from .comparison_report import ratio, total

LABELS = {
    "slsqp": "SLSQP",
    "highs3": "HiGHS · 3 referências",
    "highs5": "HiGHS · 5 referências",
    "highs5_manual": "HiGHS · 5 referências",
}
GROUPS = {
    "LAC_COW": "Vacas em lactação",
    "CALF": "Bezerras",
    "GROWING": "Novilhas em crescimento",
    "CLOSE_UP": "Pré-parto",
    "GROWING_AND_CLOSE_UP": "Novilhas em crescimento e pré-parto",
}
CONSTRAINTS = {
    "NE_total_constraint": "Energia líquida total",
    "NE_maintenance_and_activity_constraint": "Energia de manutenção e atividade",
    "NE_lactation_constraint": "Energia de lactação e gestação",
    "NE_growth_constraint": "Energia de crescimento",
    "calcium_constraint": "Cálcio digestível",
    "phosphorus_constraint": "Fósforo digestível",
    "protein_constraint_lower": "Proteína metabolizável · mínimo",
    "protein_constraint_upper": "Proteína metabolizável · máximo",
    "NDF_constraint_lower": "FDN total · mínimo",
    "NDF_constraint_upper": "FDN total · máximo",
    "forage_NDF_constraint": "FDN de forragens · mínimo",
    "fat_constraint": "Gordura · máximo",
    "DMI_constraint_lower": "Matéria seca · mínimo",
    "DMI_constraint_upper": "Matéria seca · máximo",
}


def number(value, decimals=2):
    if value is None:
        return "—"
    return f"{value:,.{decimals}f}".translate(str.maketrans(",.", ".,"))


def label(run):
    return LABELS.get(run, run)


def percent(value, signed=False):
    if value is None:
        return "—"
    sign = "+" if signed and value > 0 else ""
    return f"{sign}{number(value)}%"


def browser_data(runs):
    pens = {}
    for index, run in enumerate(runs):
        counts = {}
        for row in run["pens"]:
            pen = row["pen_id"], row["group"]
            dates = pens.setdefault(pen, {})
            dates.setdefault(row["date"], {"ingredients": {}, "nutrition": {}})
            counts[pen, row["date"]] = row["animals"]
        for table_name, field, key in (
            ("composition", "ingredient_id", "ingredients"),
            ("nutrition", "constraint", "nutrition"),
        ):
            for row in run[table_name]:
                pen = row["pen_id"], row["group"]
                rows = pens[pen][row["date"]][key]
                if key == "ingredients":
                    heading = " · ".join(filter(None, (row["ingredient_id"], row["name"])))
                    values = [row["applied_kg_dm_per_animal"], ratio(row["applied_usd"], counts[pen, row["date"]])]
                else:
                    name = CONSTRAINTS.get(row[field], row[field])
                    heading = f'{name} ({row["unit_per_animal_day"]})'
                    direction = "≥" if row["direction"] == "min" else "≤"
                    values = [
                        row["nutritional_target"],
                        row["offer"],
                        row["effective_limit"],
                        direction,
                        row["audit_status"],
                    ]
                entry = rows.setdefault(row[field], {"label": heading, "values": {}})
                entry["values"][index] = values
    options = []
    for (pen, group), dates in sorted(pens.items(), key=lambda item: (item[0][1] != "LAC_COW", item[0][0], item[0][1])):
        days = []
        for date, rows in sorted(dates.items()):
            keep = [
                entry
                for _, entry in sorted(rows["ingredients"].items(), key=lambda item: int(item[0]))
                if any(value[0] != 0 for value in entry["values"].values())
            ]
            days.append({"date": date, "ingredients": keep, "nutrition": list(rows["nutrition"].values())})
        options.append({"label": f"Lote {pen} · {GROUPS.get(group, group)}", "days": days})
    return {"runs": [label(run["run"]) for run in runs], "pens": options}


def summary_rows(runs, summaries):
    rows = []
    for run, summary in zip(runs, summaries, strict=True):
        attempts = run["attempts"]
        succeeded = sum(row["success"] is True for row in attempts) if attempts else None
        cost = summary["Custo fornecido (US$)"]
        daily_times = [row["optimization_s"] for row in run["daily"] if row["attempts"]]
        rate = ratio(succeeded, len(attempts))
        rows.append(
            {
                "Método": label(run["run"]),
                "Custo acumulado (US$)": number(cost),
                "Custo médio diário (US$/dia)": number(ratio(cost, summary["Dias"])),
                "Leite (kg)": number(summary["Leite (kg)"]),
                "Custo por kg de leite (US$/kg)": number(summary["US$/kg de leite"], 6),
                "MS fornecida (kg)": number(summary["MS fornecida (kg)"]),
                "Otimização total (s)": number(total(daily_times)),
                "Sucesso das tentativas": percent(None if rate is None else 100 * rate),
            }
        )
    return rows


def validation_rows(runs):
    rows = []
    groups = {
        "PuLP · validação NRC": ("approved", "rejected"),
        "SLSQP · avaliador legado": ("legacy_evaluator_passed", "legacy_evaluator_failed"),
    }
    for run in runs:
        by_backend = defaultdict(list)
        for row in run["attempts"]:
            if row["animal_group"] == "lac_cow":
                by_backend[row["backend"]].append(row)
        for backend, attempts in by_backend.items():
            evaluation = {"pulp": "PuLP · validação NRC", "slsqp": "SLSQP · avaliador legado"}.get(backend, backend)
            approved, rejected = groups.get(evaluation, (None, None))
            statuses = Counter(r["nutritional_validation"] for r in attempts)
            outcomes = Counter(r["success"] for r in attempts)
            rows.append(
                {
                    "Método": label(run["run"]),
                    "Critério nutricional": evaluation,
                    "Aprovadas": statuses[approved] if approved is not None else None,
                    "Rejeitadas": statuses[rejected] if rejected is not None else None,
                    "Sem resultado nesse critério": len(attempts) - statuses[approved] - statuses[rejected],
                    "Sucessos registrados": outcomes[True],
                    "Falhas registradas": outcomes[False],
                }
            )
    return rows


STYLE = """
:root{color-scheme:light;--ink:#172e2a;--muted:#455e56;--line:#ccdbd4;--green:#125945}
*{box-sizing:border-box}body{font:16px/1.55 system-ui,sans-serif;margin:0;color:var(--ink);background:#f5f8f6}
main{max-width:1240px;margin:auto;padding:clamp(1rem,4vw,3rem)}h1{font-size:clamp(2rem,4.5vw,3.5rem);line-height:1.1;margin:.25em 0}
h2{font-size:1.45rem;margin:0 0 .75rem}h3{font-size:1.08rem;margin:1rem 0 .35rem}
p{margin:.45rem 0 .85rem}.muted{color:var(--muted);font-size:.91rem}a{color:var(--green);text-underline-offset:.2em}
nav,.files,.filters,.figures{display:flex;flex-wrap:wrap;gap:.55rem 1.25rem}nav{margin:1.25rem 0 .8rem}
section{margin:1.35rem 0;padding:clamp(1rem,2.6vw,1.65rem);background:white;border:1px solid var(--line);border-radius:10px}
.table{overflow-x:auto}.table table{border-collapse:collapse;width:100%;font-size:.9rem}
th,td{padding:.55rem .7rem;text-align:left;vertical-align:top;border-bottom:1px solid var(--line)}
th{background:#eaf3ee}tbody tr:nth-child(even){background:#f8faf9}td{font-variant-numeric:tabular-nums}
th:first-child{min-width:8rem}.reading{display:block;white-space:nowrap}.reading small{color:var(--muted);margin-right:.25rem}
.filters label{display:grid;gap:.25rem;font-weight:600}select{font:inherit;color:inherit;padding:.35rem .55rem;border:1px solid #839d92;border-radius:4px;background:white}
.figures>*{flex:1 1 295px;min-width:0}figure{margin:0}img{width:100%;height:auto;display:block}
details{margin:.75rem 0}details summary{cursor:pointer;color:var(--green);font-weight:600}.files{margin:.75rem 0}
:focus-visible{outline:2px solid #186848;outline-offset:3px}
"""

SCRIPT = """
const data = JSON.parse(document.querySelector("#diet-data").textContent);
const pen = document.querySelector("#pen");
const day = document.querySelector("#day");
const number = new Intl.NumberFormat("pt-BR", {maximumSignificantDigits: 11});
const dateLabel = new Intl.DateTimeFormat("pt-BR", {timeZone:"UTC"});
const value = n => n == null ? "—" : number.format(n);
const option = (text, index) => new Option(text, index);

function reading(cell, term, result) {
  const line = document.createElement("span");
  const label = document.createElement("small");
  label.textContent = term;
  line.className = "reading";
  line.append(label, document.createTextNode(result));
  cell.append(line);
}

function renderTable(id, rows, nutrition) {
  const target = document.querySelector(id);
  const body = target.querySelector("tbody");
  body.replaceChildren();
  target.querySelector(".empty").hidden = rows.length > 0;
  for (const entry of rows) {
    const row = body.insertRow();
    const heading = document.createElement("th");
    heading.scope = "row";
    heading.textContent = entry.label;
    row.append(heading);
    for (let index = 0; index < data.runs.length; index++) {
      const cell = row.insertCell();
      const values = entry.values[index];
      if (!values) {
        cell.textContent = "—";
      } else if (nutrition) {
        const [requirement, offer, limit, direction, status] = values;
        reading(cell, "Meta", value(requirement));
        reading(cell, "Oferta", value(offer));
        reading(cell, "Limite", limit == null ? "—" : direction + " " + value(limit));
        reading(cell, "Auditoria", status || "—");
      } else {
        reading(cell, "kg MS", value(values[0]));
        reading(cell, "US$", value(values[1]));
      }
    }
  }
}

function refresh() {
  const selection = data.pens[pen.value]?.days[day.value];
  renderTable("#ingredient-view", selection?.ingredients ?? [], false);
  renderTable("#nutrition-view", selection?.nutrition ?? [], true);
}

function selectPen() {
  const previous = day.selectedOptions[0]?.dataset.date;
  const days = data.pens[pen.value]?.days ?? [];
  day.replaceChildren(...days.map((entry, index) => {
    const item = option(dateLabel.format(new Date(entry.date + "T00:00:00Z")), index);
    item.dataset.date = entry.date;
    return item;
  }));
  const match = days.findIndex(entry => entry.date === previous);
  if (match >= 0) day.value = match;
  day.disabled = days.length === 0;
  refresh();
}

pen.replaceChildren(...data.pens.map((entry, index) => option(entry.label, index)));
pen.disabled = data.pens.length === 0;
pen.addEventListener("change", selectPen);
day.addEventListener("change", refresh);
selectPen();
"""


def render(runs, summaries, deltas, biological, figures, csv_files, cell, table, details):
    payload = browser_data(runs)
    embedded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    headings = "".join(f'<th scope="col">{cell(name)}</th>' for name in payload["runs"])

    def interactive_table(identity, title, subject):
        return (
            f'<div id="{identity}"><h3>{title}</h3><p class="empty">Dados indisponíveis.</p>'
            f'<div class="table"><table><thead><tr><th scope="col">{subject}</th>{headings}'
            "</tr></thead><tbody></tbody></table></div></div>"
        )

    effects = [
        {
            "Base": label(row["baseline"]),
            "Comparação": label(row["comparison"]),
            "Diferença no custo acumulado": percent(row["cumulative_applied_usd_delta_pct"], signed=True),
        }
        for row in deltas
    ]
    economic_note = "A comparação econômica usa os preços ilustrativos fornecidos à otimização."
    if deltas and all(row["cumulative_applied_usd_delta_pct"] is not None for row in deltas):
        best = min(summaries, key=lambda row: row["Custo fornecido (US$)"])
        economic_note = f'{label(best["Execução"])} teve o menor custo acumulado entre as execuções, aos preços ilustrativos fornecidos.'
    validations = validation_rows(runs)
    linear_counts = [
        f'{row["Método"]} {row["Aprovadas"]}/{row["Sucessos registrados"] + row["Falhas registradas"]}'
        for row in validations
        if row["Critério nutricional"] == "PuLP · validação NRC"
    ]
    nutrition_note = "O atendimento depende dos limites efetivos e das tolerâncias por restrição."
    if linear_counts:
        nutrition_note = "Aprovações NRC na lactação · " + " | ".join(linear_counts) + ". " + nutrition_note
    gaps = [
        f'{label(row["Execução"])} {percent(row["Gap mediano (%)"])}'
        for row in summaries
        if row["Gap mediano (%)"] is not None
    ]
    gap_note = "Gaps medianos observados · " + " | ".join(gaps) + ". " if gaps else ""
    gap_note += "Os gaps disponíveis não comprovam otimalidade global. A instrumentação pode afetar os tempos."
    file_links = "".join(f'<a href="{cell(name)}">{cell(name)}</a>' for name in csv_files)
    png_links = "".join(
        f'<a href="{cell(name)}">{cell(title)} ({cell(name)})</a>' for name, (title, _) in figures.items()
    )

    def chart_grid(names):
        return '<div class="figures">' + "".join(figures[name][1] for name in names) + "</div>"

    sections = (
        (
            "resumo",
            "Resumo executivo",
            table(summary_rows(runs, summaries))
            + '<p class="muted">Custos da alimentação fornecida. Tempo e taxa de sucesso abrangem todos os lotes com tentativas registradas.</p>',
        ),
        ("custos", "Comparação econômica", chart_grid(("daily_cost.png", "cumulative_cost.png")) + table(effects)),
        (
            "dietas",
            "Composição e balanço nutricional",
            '<div class="filters"><label for="pen">Lote<select id="pen"></select></label>'
            '<label for="day">Dia<select id="day"></select></label></div>'
            "<noscript>Ative o JavaScript para usar os seletores ou consulte o relatório técnico.</noscript>"
            + interactive_table("ingredient-view", "Ingredientes fornecidos por animal/dia", "Ingrediente (ID e nome)")
            + interactive_table("nutrition-view", "Restrições e ofertas por animal/dia", "Restrição (unidade)")
            + '<p class="muted">A coluna Auditoria aplica a tolerância da checagem linear às margens reconstruíveis da dieta reportada. '
            "O resultado original de cada backend aparece na seção de desempenho.</p>",
        ),
        (
            "desempenho",
            "Desempenho computacional",
            chart_grid(("optimization_time.png", "gap.png", "references.png"))
            + "<h3>Formulações de lactação</h3>"
            + table(validations)
            + '<p class="muted">Sucesso registrado é o resultado da tentativa. As colunas de aprovação e rejeição seguem '
            "o critério nutricional indicado em cada linha.</p>",
        ),
        (
            "conclusoes",
            "Conclusões e limitações",
            f"<p>{cell(economic_note)} {cell(biological)}</p><p>{cell(nutrition_note)}</p>" f"<p>{cell(gap_note)}</p>",
        ),
    )
    nav = "".join(f'<a href="#{identity}">{title}</a>' for identity, title, _ in sections)
    content = "".join(
        f'<section id="{identity}"><h2>{title}</h2>{body}</section>' for identity, title, body in sections
    )
    files = '<a href="detailed_report.html">Relatório técnico completo</a>'
    files += details("Arquivos CSV", f'<div class="files">{file_links}</div>')
    files += details("Todos os gráficos PNG", f'<div class="files">{png_links}</div>')
    dates = [dt.date.fromisoformat(row["date"]) for run in runs for row in run["daily"]]
    period = f"{min(dates):%d/%m/%Y} a {max(dates):%d/%m/%Y}"
    return (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Comparação de formulações RuFaS</title><style>{STYLE}</style></head><body><main>"
        f'<h1>Comparação de formulações RuFaS</h1><p class="muted">{period}</p>'
        f'<nav aria-label="Seções do relatório">{nav}</nav>{files}{content}</main>'
        f'<script type="application/json" id="diet-data">{embedded}</script><script>{SCRIPT}</script></body></html>'
    )
