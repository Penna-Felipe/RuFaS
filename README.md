[![Flake8](https://img.shields.io/badge/Flake8-passed-brightgreen)](https://github.com/RuminantFarmSystems/MASM/actions/workflows/combined_format_lint_test_mypy.yml)
[![Pytest](https://img.shields.io/badge/Pytest-passed-brightgreen)](https://github.com/RuminantFarmSystems/MASM/actions/workflows/combined_format_lint_test_mypy.yml)
[![Coverage](https://img.shields.io/badge/Coverage-99%25-brightgreen)](https://github.com/RuminantFarmSystems/MASM/actions/workflows/combined_format_lint_test_mypy.yml)
[![Mypy](https://img.shields.io/badge/Mypy-699%20errors-red)](https://github.com/RuminantFarmSystems/MASM/actions/workflows/combined_format_lint_test_mypy.yml)


# RuFaS: Ruminant Farm Systems

**RuFaS** is an open-source, next-generation, whole-farm modeling environment that simulates dairy farm production and environmental impact. It is designed to support research, innovation, and sustainable decision-making in ruminant animal agriculture. 

---

### 🌍 Vision

A world where the continuous generation and sharing of knowledge about ruminant production systems [^note] empower understanding and decision making to achieve socio-economic well-being and environmental sustainability.
[^note]:  **RuFaS** is currently focused on dairy cattle production systems.


---

### 🎯 Mission

To develop, maintain, and share an open, modular simulation platform that connects scientific research with real world decision making. Equip scientists, farmers, and other stakeholders with tools to understand, evaluate, and improve the environmental, economic, and social outcomes of ruminant farming systems by integrating transparent models, diverse data, and collaborative contributions.
 

---

### 🧪 Scientific Foundation

RuFaS is grounded in peer-reviewed science and collaborative development. It is maintained by a diverse community of researchers, developers, and stakeholders committed to transparency, reproducibility, and continuous improvement.

---

### ♟️ Strategy

The strategic direction of RuFaS, including its vision, mission, strategic pillars, values, and operating principles, is described in [Strategy.md](Strategy.md).

---

### 🚀 Getting Started

1. **Install Python 3.12 or 3.13** - Make sure you have one of these versions installed on your system.
2. **Set up a virtual environment**
```bash
python -m venv venv
source venv/bin/activate on Mac/Linux or venv\Scripts\activate on Windows
```
3. **Install dependencies**
```bash
pip install .
```
4. **Enable output display** - Navigate to `output/output_filters/` and rename `_csv_all_variables.txt` → `csv_all_variables.txt` (remove the leading underscore).
5. **Run RuFaS**
```bash
python main.py
```
6. **Learn more** if you have further questions read through the documentation on our [GitHub Pages site](https://ruminantfarmsystems.github.io/RuFaS/) or watch our [onboarding video series](https://www.youtube.com/playlist?list=PLqq6i4QOoueR-a2mxVX3Gc78s1wvTRfr1).

---

### CLI experimental de formulação de dietas

O comando original `rufas` continua disponível para executar tarefas gerais do RuFaS. Os comandos abaixo partem do cenário experimental `animals_only` com rebanho freestall, padrão NRC, reformulação diária e preços ilustrativos. O padrão é de três dias desde 30/05/2013, semente 42, estratégia `full`, cinco referências, Midwest habilitada e HiGHS na geração de referências, no limite inferior de custo e nos LPs nutricionais. O cenário serve para comparação experimental. Uma simulação de fazenda precisa de dados próprios.

Instale em modo editável a partir da raiz do checkout. Exemplo no PowerShell com Python 3.12:

```powershell
py -3.12 -m venv .venv
.venv/Scripts/python.exe -m pip install -e '.[linear_ration_highs]'
.venv/Scripts/Activate.ps1
rufas-linear
rufas-linear --days 30 --references 3
rufas-compare
rufas-compare --days 30 --references 3 5
rufas-compare --days 30 --html
```

| Opção | Efeito |
| --- | --- |
| `--days N` | Número de dias corridos, incluindo a data inicial |
| `--seed N` | Semente fixa, de 1 a 4294967295, compartilhada entre os métodos |
| `--output PATH` | Pasta pai para novos diretórios exclusivos. Padrão `output/ration_cli` no checkout |
| `--metadata PATH` | Metadados da simulação com seu próprio cadastro de entradas. Os caminhos internos seguem a raiz do checkout, como no uso padrão do RuFaS, ou podem ser absolutos |
| `--config PATH` | Configuração de simulação que substitui a configuração apontada pelos metadados. A CLI aplica a duração solicitada à data inicial e ativa a semente fixa |
| `--references N [N ...]` | Orçamento de referências do HiGHS, com valor padrão 5. `rufas-linear` recebe um único orçamento |
| `--methods slsqp highs` | Métodos de `rufas-compare` em ordem de execução. O primeiro de cada par é a base da diferença |
| `--strategy single\|full\|adaptive_gap`, `--gap-target F` | Estratégia e meta de gap como fração, por exemplo `0.05` para 5%. A meta controla parada antecipada em `adaptive_gap` |
| `--midwest` / `--no-midwest` | Habilita ou desabilita a referência regional |
| `--verbosity none\|credits\|errors\|warnings\|logs` | Exibe o log de console da execução ao final no nível escolhido. O padrão mantém o terminal conciso e arquiva os logs |
| `--html` | Gera os relatórios resumido e técnico e seus gráficos |

PuLP/HiGHS é aplicado à formulação automática NRC na lactação. Os demais grupos seguem os fluxos originais. Para metadados personalizados, forneça um cenário com módulo animal e, se usar HiGHS, padrão NRC e formulação automática. O preparador usa os arquivos versionados para o cenário padrão e grava cópias das configurações alteradas. Cada braço recebe seus próprios arquivos de tarefa, saída e log.

A tabela do terminal usa custos de alimentação fornecida, valorizados aos preços de entrada. A média em lactação é ponderada por vaca-dia. A tabela de desempenho registra tentativas de todos os lotes e apresenta à parte os critérios nutricionais na lactação. O SLSQP reporta seu avaliador legado, e o HiGHS reporta a validação NRC do backend linear. A conclusão exige registro do TaskManager, calendário completo, semente e backend confirmados no JSON. O comando sinaliza falha com código diferente de zero e mantém os artefatos já produzidos.

A pasta anunciada no terminal contém `terminal_summary.json`, `batch.json`, as entradas, os JSONs brutos, os logs e os CSVs em `report/`. Com `--html`, abra `report/index.html` na pasta indicada. Os gráficos são gerados somente quando essa opção é usada. [Estrutura dos relatórios](helpful_scripts/nrc_ration_comparison/comparison_report.md)

---


### 🤝 How to Contribute

RuFaS welcomes coding and noncoding contributions from individuals demonstrating interest and commitment to our program standards. You can:
- 🧪 Test features and report bugs
- 💡 Suggest new features or improvements
- 🗣️ Engage in scientific discussions and peer reviews
- 💻 Submit code, documentation, or scientific literature
- 🧰  Help with user support and onboarding
- 🎨  Design user interfaces or visual assets
- 📣  Promote RuFaS within your networks

> Please see the [![Contributor Covenant](https://img.shields.io/badge/Contributor%20Covenant-2.1-4baaaa.svg)](https://www.contributor-covenant.org/version/2/1/code_of_conduct/code_of_conduct.md) code of conduct and [CONTRIBUTING.md](https://github.com/RuminantFarmSystems/RuFaS/blob/dev/CONTRIBUTING.md?plain=1) for full details.

> For prerequisites and testing read the [PREREQUISITES](https://ruminantfarmsystems.github.io/RuFaS/_wiki/Github-Actions.html) and [End-to-End Testing](https://ruminantfarmsystems.github.io/RuFaS/_wiki/End%E2%80%90to%E2%80%90End-Testing.html) files.

---

### 📜 License

RuFaS is licensed under GPLv3. See the [COPYING.md](https://github.com/RuminantFarmSystems/RuFaS/pull/2369) and [COPYING.LESSER.md](https://github.com/RuminantFarmSystems/RuFaS/pull/2369) files for details.

---

## 📬 Contact

For questions, sponsorship inquiries, or collaboration proposals, please email contact@rufas.org.

---

## 🧑‍🔬 Acknowledgements

Thanks to all the [individuals](https://www.rufas.org/the-team) and [organizations](https://www.rufas.org/partners) that contributed to RuFaS development and maintenance in the past and continue to contribute today. Contributions to the RuFaS GitHub repository are recorded [here](https://github.com/RuminantFarmSystems/RuFaS/graphs/contributors).
