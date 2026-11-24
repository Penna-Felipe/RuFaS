# Estado do projeto RuFaS — formulação linear NRC

**Atualizado em 24 de novembro de 2026.** Use este documento para retomar o desenvolvimento. Os resultados arquivados já permitem iniciar o próximo piloto. Os comandos abaixo servem para reprodução seletiva.

## Objetivo e decisão vigente

O projeto acadêmico investiga a qualidade econômica, a viabilidade nutricional, a estabilidade e o desempenho de dietas para vacas em lactação formuladas por programação linear no RuFaS. O comparador é o `RationOptimizer` original, com SciPy/SLSQP. A comparação controla exigências, ingredientes, preços, limites e critérios de aprovação. Deve separar o efeito do solver, da referência e da trajetória do rebanho.

**Decisão explícita:** manter a abordagem de **coeficientes nutricionais fixos**, preservar as equações NRC originais e suas tolerâncias e **não implementar Taylor ou programação linear sequencial neste momento**. A abordagem reaproveita as equações de oferta, é simples de manter e permite certificar as candidatas com o NRC. SLSQP permanece como padrão e comparador. Falhas do PuLP em grupos elegíveis são registradas e seguem o tratamento existente da Pen, sem fallback automático para SLSQP.

## Fundamentação matemática

- A variável xᵢ é a quantidade de MS do ingrediente de `rufas_id` i, em kg/vaca/dia. Minimiza-se Σ pᵢxᵢ com preços pᵢ em US$/kg MS. O `RationConfig` fornece os mesmos ingredientes, preços e limites aos dois backends.
- O LP básico contém limites individuais e oito linhas de dieta: piso e teto de MS, cálcio e fósforo digestíveis, piso e teto de FDN total, mínimo de FDN de forragem e máximo de gordura. Com MS positiva, multiplicar as restrições percentuais pela MS total preserva o sinal e produz linhas exatamente equivalentes. Os valores são 25%–45% de FDN total, mínimo de 15% de FDN de forragem e máximo de 7% de gordura. A exigência de fósforo é o máximo entre o requisito nutricional e o de processo. Na modalidade `predict_DMI`, o piso de MS usa 70% da exigência corrente e o teto usa 130% da meta inicial.
- **Energia.** Na dieta de referência, o `NutritionSupplyCalculator` calcula o desconto de ingestão a partir de MS, TDN e peso médio. O desconto, DE e ME por ingrediente ficam fixos. As ofertas de energia líquida de manutenção, crescimento e lactação são somas de coeficientes em Mcal/kg MS vezes xᵢ. Aplicam-se os pisos individuais. A condição max(ELman, ELcres, ELlact) ≥ exigência total é a união de três alternativas. A mesma candidata pode aparecer em mais de uma.
- **Proteína.** A referência fixa participação de concentrados, taxas de passagem, RDP e RUP. Em g/vaca/dia, a oferta é 0,64 × min(M_TDN, M_RDP) + RUP digestível + 4,72 × Σ xᵢ. Os totais microbianos decorrem de 0,13 × TDN descontado e 0,85 × RDP, convertidos para gramas. Cada regime impõe qual ramo é menor, o piso atual de PM e o teto de 1,5 vezes a exigência inicial. Cada referência gera **3 × 2 = 6 LPs**. Mudanças no desconto ou na passagem entre referência e candidata podem alterar as ofertas e o ramo microbiano efetivo.
- **Certificação.** Um ótimo LP é uma candidata. `RationOptimizer.set_constraints()` fornece as **14 funções NRC originais** avaliadas sem executar SLSQP. Validam-se quantidades por ID, limites individuais e os vetores bruto e arredondado a seis casas. Só se tenta reparo se o bruto passa e o arredondado falha. O reparo verifica até 32 vizinhos de um ingrediente, com passo ±0,000001 kg MS, ordenados por distância ao vetor bruto, custo e ID. Cada tentativa passa pelas 14 regras. Tolerâncias absolutas por unidade: MS e limites individuais 1e−7 kg, minerais e PM 1e−5 g, energia 1e−6 Mcal, fibra e gordura 1e−6 ponto percentual.
- **Limite e gap.** O LP básico relaxa o problema ao retirar energia e PM. Usa a mesma função objetivo e os mesmos limites. `primary_lower_bound()` usa o problema primário, sem os desempates da geração, e calcula um limite dual conservador compatível com as tolerâncias do validador. O gap é (U−L)/U para custo aprovado U positivo, com tratamento explícito de limite nulo, negativo, ausente ou inconsistente. A meta inicial é 5%. O resultado é a melhor dieta validada encontrada entre as candidatas exploradas. O limite pode ser fraco, e o resultado não estabelece o ótimo global do NRC.

## Arquitetura e integração

| Arquivo | Responsabilidade |
|---|---|
| [ration_optimizer.py](RUFAS/biophysical/animal/ration/ration_optimizer.py) | `RationConfig` ativo, funções NRC originais, objetivo e SLSQP. |
| [nutrition_supply_calculator.py](RUFAS/biophysical/animal/nutrients/nutrition_supply_calculator.py) e [nrc_requirements_calculator.py](RUFAS/biophysical/animal/nutrients/nrc_requirements_calculator.py) | Ofertas e exigências NRC. `Animal.set_nutrition_requirements()` usa o estado corrente e informações da oferta anterior. |
| [linear_ration_optimizer.py](RUFAS/biophysical/animal/ration/linear_ration_optimizer.py) | `_build_problem`, `calculate_nrc_energy_coefficients`, `calculate_nrc_protein_coefficients`, `solve_nrc_cases`, `validate_nrc_candidate` e `solve_and_validate_nrc_cases`. Monta o LP, calcula fatores, resolve, valida e repara. |
| [linear_reference.py](RUFAS/biophysical/animal/ration/linear_reference.py) | `build_basic_reference` gera menor custo, máxima forragem, máximo concentrado ou menor desvio absoluto de MS da meta. Desempata lexicograficamente por custo quando pertinente e por ID. `reference_issue` verifica domínio e limites individuais. `grid_key` elimina repetições na malha de seis casas. Uma referência pode falhar no NRC vigente. |
| [linear_cost_bound.py](RUFAS/biophysical/animal/ration/linear_cost_bound.py) | `primary_lower_bound`, `dual_bound`, `relative_gap` e `meets_target`. Relaxação, certificação conservadora do limite e critério de parada. |
| [linear_ration_adapter.py](RUFAS/biophysical/animal/ration/linear_ration_adapter.py) | `LinearRationAdapter.attempt_optimization` implementa o contrato da Pen com `RationConfig` e `OptimizeResult`. Explora referências sob demanda, guarda a melhor aprovada e distingue inviabilidade de LP, falha do solver, ausência de referência e rejeição NRC. `make_ration_from_solution` usa o mapa aprovado por ID. |
| [ration_backend_config.py](RUFAS/biophysical/animal/ration/ration_backend_config.py) | `RationBackendConfig` valida as opções e determina a elegibilidade. |
| [herd_manager.py](RUFAS/biophysical/animal/herd_manager.py), [pen.py](RUFAS/biophysical/animal/pen.py) e [schema](RUFAS/input/metadata/properties/default.json) | Propagam configuração, despacham, tratam a tentativa, aplicam a dieta e registram as métricas. |
| [pyproject.toml](pyproject.toml) | Extra opcional `linear_ration` com `PuLP>=3.0,<4`. `highspy` está somente no experimento isolado. |

Fluxo diário: `SimulationEngine._execute_ration_planning()` → `_formulate_ration()` → `HerdManager.formulate_rations()` → `_reformulate_ration_single_pen()` → `Pen.formulate_optimized_ration()` → `_attempt_formulation()`. A Pen fornece as exigências agregadas e `Pen.ration` por ID. `_apply_successful_solution()` usa o backend que resolveu a tentativa e calcula a oferta individual. `_record_ration_attempt()` grava `ration_optimizer_attempt_pen_{id}` com dia, baia, grupo, backend e motivo, custo, estratégia, referência escolhida, limite, meta e gap alcançado, tempo, chamadas e status. Os módulos de produção são independentes de `helpful_scripts`.

O `RationManager` resolve a lista de ingredientes por grupo. `AvailableFeedsBuilder` usa o arquivo de alimentação escolhido nos metadados e a tabela [NRC_comp.csv](input/data/feed/NRC_comp.csv). `purchased_feed_cost` é US$/kg MS. O [exemplo Midwest](input/data/feed/example_Midwest_feed.json) contém proporções explícitas, usadas também para referências experimentais. A primeira formulação recebe uma dieta anterior vazia. Nas reformulações, a dieta anterior pode ser incompatível com ingredientes, limites ou exigências atuais. O custo formulado é por animal/dia. O custo aplicado usa as quantidades diárias da baia com os preços de entrada. O modo `animals_only` registra as quantidades físicas de alimentação, sem apurar pagamentos efetivos de aquisição.

Exemplo de configuração em `animal.ration`:

```json
{
  "user_input": false,
  "formulation_interval": 1,
  "optimizer_backend": "pulp",
  "linear_strategy": "adaptive_gap",
  "linear_gap_target": 0.05,
  "linear_max_references": 5
}
```

O backend padrão é SLSQP. PuLP atende **NRC, LAC_COW e formulação automática**. Os demais grupos e modalidades mantêm o fluxo original, com dieta direta para CALF. A produção tenta a dieta anterior compatível primeiro e depois os quatro objetivos básicos na ordem listada. `single` usa a primeira referência utilizável, `full` explora até o orçamento e `adaptive_gap` pode parar ao atingir a meta. Ao esgotar o orçamento, retorna a melhor dieta aprovada disponível. Midwest ainda é experimental.

## Experimentos e principais resultados

Os JSONs históricos desta tabela ficam em `helpful_scripts/nrc_ration_comparison/`, salvo quando o caminho começa em `output/`. Custos unitários são US$/vaca/dia.

| Etapa | Scripts e artefatos | Resultados |
|---|---|---|
| Vaca 114502, SLSQP e Midwest | [compare.py](helpful_scripts/nrc_ration_comparison/compare.py), `results.json`, `results_repaired.json` | SLSQP 0,275284. PuLP teve dois ótimos e quatro inviáveis. Os dois ótimos inicialmente falharam após arredondar e passaram com reparo. Custo PuLP reparado 0,290385. |
| Sensibilidade | [sensitivity.py](helpful_scripts/nrc_ration_comparison/sensitivity.py), `sensitivity_results.json` | PuLP 0,290385 com Midwest, 0,286528 com forragem duplicada e normalizada, 3,201165 com a solução SLSQP como referência exclusivamente diagnóstica. |
| Múltiplas referências | [multireference.py](helpful_scripts/nrc_ration_comparison/multireference.py), `multireference_results.json` | LP básico de menor custo gerou a vencedora, 0,274553 versus 0,275284 do SLSQP observado. As energias coincidiram porque o desconto de TDN permaneceu 1. PM aproximada ficou 23,52 g abaixo da original, pela RUP digestível. |
| Adaptação por viabilidade, 12 cenários | [adaptive.py](helpful_scripts/nrc_ration_comparison/adaptive.py), `adaptive_results.json` | Três vacas, dois cardápios, dois regimes de preços, semente 42. Single, adaptativa e full aprovaram 12/12. Full melhorou 8/12 custos. SLSQP aprovou 8/12 nesse protocolo. |
| Adaptação por gap | [gap_experiment.py](helpful_scripts/nrc_ration_comparison/gap_experiment.py), `gap_results.json` | Metas 1%, 3%, 5% e 10% atingidas em 1, 3, 6 e 6 de 12. As estratégias e o SLSQP com reparo equivalente aprovaram 12/12. A 5%, máximo de US$ 0,003197 acima de full, ante US$ 6,370717 da estratégia que para na primeira dieta viável. |
| CLI real, três dias | [Relatório CLI](helpful_scripts/nrc_ration_comparison/cli_three_day_report.md), `output/nrc_cli_three_day/summary.json` | `animals_only`, freestall, dias julianos 150–152/2013, semente 42. SLSQP, full e adaptive_gap completaram três dias. Single completou dois. Full e adaptive_gap retornaram dietas idênticas, com 4/5/5 referências, 60/66/66 chamadas por dia e gaps de 25,39%, 32,11% e 95,15%. |
| Reprodução isolada da CLI | [Relatório da auditoria](helpful_scripts/nrc_ration_comparison/cli_isolated_audit_report.md), [script](helpful_scripts/nrc_ration_comparison/cli_isolated_audit.py), `output/nrc_cli_three_day/isolated_audit.json` | 15 tentativas e 189 avaliações arquivadas, com paridade nos 14 resíduos e nas seleções PuLP. No problema full do terceiro dia, SLSQP aprovou 0,369054 com semente diagnóstica 43. O arranque pela dieta anterior produziu 0,362986 no bruto, rejeitado após arredondamento e reparo. |
| Benchmark de precisão e referências externas | [Relatório do benchmark](helpful_scripts/nrc_ration_comparison/solver_benchmark_report.md), [script](helpful_scripts/nrc_ration_comparison/solver_benchmark.py), `output/nrc_solver_benchmark/results.json` | 552 casos principais em 27 formulações, cinco repetições por caso e interface. A etapa separada de Midwest tem 162 LPs adicionais por solver. |

Na CLI, os valores acumulados de alimento aplicado à lactação foram US$ 88,23 no SLSQP e US$ 504,56 em full e adaptive_gap. Os três cenários completos produziram 9.659,51 kg de leite. Single acumulou US$ 440,18 em dois dias. As comparações de diferentes trajetórias usam esses totais apenas descritivamente. A auditoria isolada controlou as exigências em cada comparação.

### CBC versus HiGHS

| Interface | Brutos aprovados | Aprovações finais | Mediana por LP |
|---|---:|---:|---:|
| CBC 2.10.3 textual, configuração atual | 187 | 168 | 26,57 ms |
| CBC textual, tolerâncias primal e dual de 1e−9 | 187 | 168 | 26,33 ms |
| CBC textual, `outputFormat 4` | 187 | 168 | 26,37 ms |
| CBC, saída binária experimental | 264 | 223 | 54,07 ms |
| PuLP 3.3.2 / highspy 1.16.0 direto, uma thread | 264 | 223 | 2,15 ms |
| SciPy 1.18.1 / HiGHS interno 1.12.0 | 264 | 223 | 4,46 ms |

Todos deram 466 ótimos e 86 inviáveis. Os três caminhos de maior precisão recuperaram os mesmos 56 casos, perderam um após reparo, reduziram o melhor custo em oito formulações e mantiveram 23/27 formulações aprovadas no conjunto principal. Em cada ótimo, o texto CBC coincidiu com o vetor binário da mesma execução arredondado a oito algarismos significativos. A maior diferença em um ingrediente foi 4,984e−7 kg. Apertar tolerâncias ou mudar `outputFormat` manteve o texto idêntico. O MPS do PuLP usa 13 algarismos significativos. O [controle MPS](output/nrc_solver_benchmark/mps_precision_control.json) alimentou HiGHS com os mesmos valores decimais do MPS e preservou estados e aprovações dos 552 casos. Os tempos incluem interface, processo e arquivos quando aplicável. Excluem geração de referências, validação e reparo. O leitor binário experimental gravou os dois formatos para pareamento.

No terceiro dia de full, a saída de maior precisão aprovou **0,369587** com referência de meta de MS e o reparo atual, ante **5,691552** na saída textual. Acrescentar Midwest mantendo o solver fixo elevou a aprovação de **23/27 para 27/27** no CBC e no PuLP/HiGHS. Entre as formulações que já passavam, reduziu o custo em sete no CBC e quatro no HiGHS. Na primeira tentativa single do terceiro dia, retornou 0,406778 nos dois. Midwest foi renormalizada para a MS-alvo após excluir os IDs 301 e 302, que somavam 28,48% da receita. O cardápio e os preços do LP permaneceram iguais. Os outros exemplos integrais tinham IDs fora dos cardápios. As tentativas posteriores à redução de leite são comparações condicionais com as entradas arquivadas.

## Problemas, causas e limitações

- **Precisão no vetor bruto.** No terceiro dia, os casos de menor custo básico e meta de MS excederam o teto bruto em 1,50e−7 e 3,40e−7 kg. A tolerância é 1e−7 kg. As mesmas matrizes passaram com vetor de maior precisão e o reparo existente. Reparo de arredondamento exige aprovação bruta.
- **Aproximação nutricional.** Ainda houve 202 ótimos rejeitados por aproximação na etapa bruta e 41 que passaram no bruto e falharam após arredondamento e reparo, mesmo em alta precisão. Nas candidatas baratas do terceiro dia com desconto 1, a energia coincidia e o erro de PM vinha da RUP digestível. Na dieta cara, o desconto real foi 0,82518 ante o valor congelado de 1. Houve troca de RDP para TDN como limitante e superestimação de 233,51 g de PM. Os IDs 44 e 167 representaram 94,4% do custo da dieta cara.
- **Single e tratamento da Pen.** Os 12 ótimos das três tentativas single no terceiro dia excederam o teto original de PM em aproximadamente 2 a 164 g. Reduzir leite baixou os pisos, mas preservou a referência e o teto de PM ancorado. A Pen já lançava a exceção de limite de redução antes de chegar a `_finalize_ration_outcome()` no fluxo anterior à integração. Reaplicar a dieta anterior teria excedido o teto de MS em 0,175181 kg/vaca mesmo após a última redução. Também faltavam 0,042024 g de cálcio na primeira tentativa.
- **Gap pouco informativo nos dias da CLI.** O limite básico ficou próximo de 0,28. O salto de custo da dieta aprovada levou o gap a 95,15%. Mesmo a dieta aprovada de 0,369587 teria gap aproximado de 25,36%, acima da meta de 5%. O limite omite energia e PM.
- **Generalização.** Uma população e uma semente em três dias de `animals_only`, preços ilustrativos e cardápios limitados. A comparação de matrizes congelou a geração das referências. Os tempos medem a resolução isolada e sua interface. A simulação recalcula as exigências a partir do estado animal e da oferta anterior. O indicador legado de gordura da Pen deve ser interpretado separadamente dos resíduos NRC do otimizador.

## Próximas etapas, por prioridade

1. **Preservar os arquivos e artefatos do workspace** antes de trocar de checkout. Registrar a revisão exata dos próximos experimentos. Usar os resultados arquivados para iniciar o trabalho.
2. **Pilotar PuLP/HiGHS direto apenas nos seis casos nutricionais.** Manter inicialmente CBC na geração de referências e no cálculo do limite. Usar as matrizes congeladas como regressão, com validação por ID, vetor bruto, arredondado e reparado. SLSQP continua padrão. CBC binário é uma alternativa diagnóstica se for preciso conservar CBC. Uma troca também no gerador e no limite exige validação própria.
3. **Adicionar uma opção de referência independente compatível.** Definir projeção da receita, orçamento e gatilho para explorar a alternativa. Usar Midwest como exemplo, manter ingredientes e preços fixos e testar o efeito com o mesmo solver. A solução SLSQP permanece exclusivamente diagnóstica.
4. **Tratar separadamente a exceção da Pen e a possível reutilização.** Exercitar o limite de redução de leite e revalidar dieta anterior diante das exigências correntes. Distinguir falha computacional, ausência de candidata e dieta anterior fora das restrições.
5. **Repetir uma simulação curta após o piloto e ampliar os cenários gradualmente.** Medir tempo integral, custo, leite, consumo, referências, gaps e falhas. Investigar preços mais representativos e relaxações comprovadas que fortaleçam o limite. Preservar os coeficientes fixos e a certificação original.

## Testes e reprodução

Marcos reportados anteriormente: 87 testes do núcleo, 138 após validação e seleção, 182 após o adaptador e **1.151 testes relacionados após a integração**. Depois da integração, as auditorias conferiram resíduos, matrizes e resultados, e o benchmark passou por um smoke test com seis regimes. Esta atualização documental não executou testes novamente.

- Produção: [test_linear_ration_optimizer.py](tests/test_biophysical/test_animal/test_ration/test_linear_ration_optimizer.py), [test_linear_ration_adapter.py](tests/test_biophysical/test_animal/test_ration/test_linear_ration_adapter.py) e [test_ration_backend_integration.py](tests/test_biophysical/test_animal/test_pen/test_ration_backend_integration.py). Suítes existentes nas pastas `test_ration/`, `test_pen/` e `test_herd_manager/`.
- Experimentos: `test_sensitivity.py`, `test_multireference.py`, `test_adaptive.py` e `test_gap_experiment.py` em `helpful_scripts/nrc_ration_comparison/`.

Comandos PowerShell a partir da raiz:

```powershell
py -3.12 -m pip install -e '.[linear_ration,dev]'
py -3.12 -m pytest -q -p no:cacheprovider tests/test_biophysical/test_animal/test_ration tests/test_biophysical/test_animal/test_pen tests/test_biophysical/test_animal/test_herd_manager helpful_scripts/nrc_ration_comparison
```

Experimentos históricos, escrevendo em caminhos novos:

```powershell
py -3.12 -m helpful_scripts.nrc_ration_comparison.compare --runs 5 --output output/nrc_compare_repro.json
py -3.12 -m helpful_scripts.nrc_ration_comparison.sensitivity --runs 5 --output output/nrc_sensitivity_repro.json
py -3.12 -m helpful_scripts.nrc_ration_comparison.multireference --runs 5 --output output/nrc_multi_repro.json
py -3.12 -m helpful_scripts.nrc_ration_comparison.adaptive --runs 3 --seed 42 --output output/nrc_adaptive_repro.json
py -3.12 -m helpful_scripts.nrc_ration_comparison.gap_experiment --runs 1 --output output/nrc_gap_repro.json
```

CLI de três dias. Use um diretório novo. O script verifica o marcador de conclusão além do código de saída, pois a CLI original registrou a falha de single e retornou zero.

```powershell
$scenarioScript = 'helpful_scripts/nrc_ration_comparison/cli_three_day.py'
$scenarioBase = 'output/nrc_cli_repro'
py -3.12 $scenarioScript --base $scenarioBase prepare
py -3.12 $scenarioScript --base $scenarioBase slsqp
py -3.12 $scenarioScript --base $scenarioBase single
py -3.12 $scenarioScript --base $scenarioBase full
py -3.12 $scenarioScript --base $scenarioBase adaptive_gap
```

A captura com `cli_three_day_trace.py` e a consolidação com `cli_three_day_summary.py` estão detalhadas no [relatório CLI](helpful_scripts/nrc_ration_comparison/cli_three_day_report.md). Com os registros existentes, a auditoria e o benchmark podem ser reproduzidos sem a simulação:

```powershell
py -3.12 -m helpful_scripts.nrc_ration_comparison.cli_isolated_audit --output output/nrc_cli_three_day/isolated_audit_repro.json
py -3.12 -m pip install --no-deps --target output/nrc_solver_benchmark/deps highspy==1.16.0
$env:PYTHONPATH = 'output/nrc_solver_benchmark/deps'
$solverOutput = 'output/nrc_solver_benchmark_repro'
py -3.12 -m helpful_scripts.nrc_ration_comparison.solver_benchmark --runs 5 --output $solverOutput
py -3.12 -m helpful_scripts.nrc_ration_comparison.solver_benchmark --mps-check --output $solverOutput
```

O benchmark lê `output/nrc_cli_three_day/isolated_audit.json` por padrão, além de `output/nrc_cli_three_day/inputs/feed.json` e `helpful_scripts/nrc_ration_comparison/adaptive_results.json`. Passe `--audit` para apontar a outro arquivo de auditoria. Se usar o relatório novo gerado acima, passe a mesma opção na execução principal e no controle MPS.

## Estado do Git e artefatos locais

Antes de criar este documento, a branch era **`feature/pulp-optimizer`**, sem upstream, no **`HEAD e67d64e70`** (merge PR #3373, `ndf-fract-to-perc`). Havia **quatro arquivos versionados modificados, 31 arquivos novos não versionados e nenhum arquivo em stage**. Este documento é o 32º não versionado. O `HEAD` difere do commit `41e849aa4` citado no relatório da auditoria do fluxo legado da Pen. Há mudanças upstream entre essas revisões em `nrc_requirements_calculator.py`. Antes de exigir igualdade em uma nova execução, confirme a revisão e as exigências daquele experimento.

**Versionados com mudanças locais**

- `RUFAS/biophysical/animal/herd_manager.py`
- `RUFAS/biophysical/animal/pen.py`
- `RUFAS/input/metadata/properties/default.json`
- `pyproject.toml`

**Novos em `RUFAS/biophysical/animal/ration/`**

- `linear_cost_bound.py`, `linear_ration_adapter.py`, `linear_ration_optimizer.py`, `linear_reference.py` e `ration_backend_config.py`.

**Novos em `tests/test_biophysical/test_animal/`**

- `test_pen/test_ration_backend_integration.py`
- `test_ration/test_linear_ration_adapter.py`
- `test_ration/test_linear_ration_optimizer.py`

**Novos em `helpful_scripts/nrc_ration_comparison/`**

- `compare.py`, `results.json`, `results_repaired.json`.
- `sensitivity.py`, `sensitivity_results.json`, `test_sensitivity.py`.
- `multireference.py`, `multireference_results.json`, `test_multireference.py`.
- `adaptive.py`, `adaptive_results.json`, `test_adaptive.py`.
- `gap_experiment.py`, `gap_results.json`, `test_gap_experiment.py`.
- `cli_three_day.py`, `cli_three_day_summary.py`, `cli_three_day_trace.py`, `cli_three_day_report.md`.
- `cli_isolated_audit.py`, `cli_isolated_audit_report.md`.
- `solver_benchmark.py`, `solver_benchmark_report.md`.

**Ignorados pelo Git e disponíveis neste workspace**

- `output/nrc_cli_three_day/` contém cópias de entrada, saídas por configuração, `summary.json` e `isolated_audit.json`.
- `output/nrc_cli_three_day_diagnostic/` contém `runs/*/attempts.jsonl` e o relatório parcial de single. Há capturas intermediárias em `output/nrc_cli_three_day_trace/` e `output/nrc_cli_three_day_diagnostic_partial/`.
- `output/nrc_solver_benchmark/` contém `results.json`, com matrizes, vetores, resíduos e tempos, `mps_precision_control.json`, o manifesto de progresso e highspy em `deps/`.

Para retomar no mesmo workspace, comece pelo relatório do benchmark e pelos JSONs arquivados. Para retomar em outro checkout ou computador, preserve as alterações locais e os artefatos ignorados listados. Esta etapa acrescentou somente o documento.

