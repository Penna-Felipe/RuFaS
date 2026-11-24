# Estado do projeto RuFaS — formulação linear NRC

**Atualizado em 24 de novembro de 2026.** Implementação e experimentos pausados para a apresentação acadêmica. Este documento consolida o método, os resultados e o material de reprodução.

## Objetivo e decisão vigente

O projeto acadêmico investiga a qualidade econômica, a viabilidade nutricional, a estabilidade e o desempenho de dietas para vacas em lactação formuladas por programação linear no RuFaS. O comparador é o `RationOptimizer` original, com SciPy/SLSQP. A comparação controla exigências, ingredientes, preços, limites e critérios de aprovação. Deve separar o efeito do solver, da referência e da trajetória do rebanho.

**Decisão explícita:** manter a abordagem de **coeficientes nutricionais fixos**, preservar as equações NRC originais e suas tolerâncias e **não implementar Taylor ou programação linear sequencial neste momento**. A abordagem reaproveita as equações de oferta, é simples de manter e permite certificar as candidatas com o NRC. SLSQP permanece como padrão e comparador. Falhas do PuLP em grupos elegíveis são registradas e seguem o tratamento existente da Pen, sem fallback automático para SLSQP.

## Síntese para a apresentação acadêmica

**Pergunta.** É possível reduzir o custo computacional da formulação diária de dietas no RuFaS usando programação linear e mantendo a avaliação nutricional original do NRC?

**Método.** O RuFaS fornece cardápio, preços, limites e exigências da baia. A busca fixa, em cada dieta de referência, os fatores nutricionais dependentes da composição da dieta. Resolve seis LPs por referência, combinando três condições de energia total com dois regimes de proteína microbiana. A dieta de menor custo entre as candidatas certificadas é aplicada por ID. A certificação reavalia as 14 funções NRC, com tolerâncias originais, arredondamento e reparo local. Uma relaxação das oito restrições básicas fornece um limite inferior certificado. O gap compara a dieta aprovada com esse limite.

**Evidência experimental.** A comparação em matrizes congeladas valoriza o controle experimental. Nas 552 matrizes, HiGHS aumentou as aprovações finais de 168 para 223 frente à interface textual de CBC. No piloto de referências, a mediana de geração caiu de 818 para 49 ms. Nas 35 execuções replicadas de três dias, HiGHS integral reduziu a mediana de otimização de lactação em `full` de 7,467 s com CBC e 4,376 s com HiGHS apenas nos casos nutricionais para 0,608 s. Os dois modos HiGHS selecionaram as mesmas dietas nesse ensaio. As 27 formulações arquivadas aprovaram com Midwest ligada e desligada, e a inclusão melhorou o custo de duas ou três formulações conforme o orçamento. A suíte mais recente teve **713 testes aprovados**.

| Exploração de 30 dias | SLSQP | HiGHS full 3 + Midwest | HiGHS full 5 + Midwest |
|---|---:|---:|---:|
| Dias completos | 30 | 30 | 30 |
| Reformulações bem-sucedidas na lactação | 30/30 | 30/30 | 30/30 |
| Custo total de alimento aplicado, US$ | 1.226,76 | 1.256,07 | 1.248,65 |
| Leite acumulado, kg | 98.923,12 | 99.814,17 | 99.814,17 |
| Matéria seca aplicada, kg | 104.501,78 | 105.120,64 | 105.120,64 |
| Custo alimentar por kg de leite, US$ | 0,012401 | 0,012584 | 0,012510 |
| Otimização de lactação, s | 3,26 | 5,33 | 10,38 |
| Tempo total da CLI, s | 65,66 | 68,24 | 73,21 |
| Midwest avaliada / vencedora | — | 30 / 0 | 1 / 0 |
| Gap mediano | — | 24,18% | 24,19% |

**Conclusão preliminar.** As duas configurações lineares completaram a janela de 30 dias com dietas certificadas e aplicadas exatamente por ID. O orçamento cinco custou US$ 7,42 a menos que o três, com a mesma produção de leite e mais que o dobro das chamadas nutricionais e auxiliares na lactação. As economias observadas nos casos estáticos com Midwest não reapareceram como vitórias da referência nessa trajetória. O resultado ilustra o compromisso entre ampliar a busca e limitar o trabalho por reformulação.

**Limites da interpretação.** Coeficientes fixos aproximam as ofertas de energia e proteína. Por isso, ótimos de LP podem ser rejeitados pelo NRC. O limite omite energia e proteína e nenhum gap de 30 dias atingiu 5%. Nas trajetórias, as dietas alteraram exigências futuras. Houve uma semente, preços ilustrativos, uma repetição por configuração e processos concorrentes na rodada de 30 dias. A verificação estrita das dietas SLSQP foi diagnóstica. O ensaio longitudinal carece de braço com Midwest desabilitada para atribuir efeito à receita.

**Próximas perguntas.** Generalizar referências externas, estudar a geração dinâmica de referências preservando coeficientes fixos por LP e medir sensibilidade a preços. Um ensaio longitudinal com Midwest ligada e desligada no mesmo orçamento, mais populações e sementes permitiria medir robustez e efeito isolado.

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
| [regional_reference.py](RUFAS/biophysical/animal/ration/regional_reference.py) | Lê a receita opcional Midwest, projeta sobre o cardápio NRC e registra a participação retida. |
| [linear_cost_bound.py](RUFAS/biophysical/animal/ration/linear_cost_bound.py) | `primary_lower_bound`, `dual_bound`, `relative_gap` e `meets_target`. Relaxação, certificação conservadora do limite e critério de parada. |
| [linear_ration_adapter.py](RUFAS/biophysical/animal/ration/linear_ration_adapter.py) | `LinearRationAdapter.attempt_optimization` implementa o contrato da Pen com `RationConfig` e `OptimizeResult`. Explora referências sob demanda, guarda a melhor aprovada e distingue inviabilidade de LP, falha do solver, ausência de referência e rejeição NRC. `make_ration_from_solution` usa o mapa aprovado por ID. |
| [ration_backend_config.py](RUFAS/biophysical/animal/ration/ration_backend_config.py) | `RationBackendConfig` valida as opções e determina a elegibilidade. |
| [herd_manager.py](RUFAS/biophysical/animal/herd_manager.py), [pen.py](RUFAS/biophysical/animal/pen.py) e [schema](RUFAS/input/metadata/properties/default.json) | Propagam configuração, despacham, tratam a tentativa, aplicam a dieta e registram as métricas. |
| [pyproject.toml](pyproject.toml) | Extra opcional `linear_ration` com `PuLP>=3.0,<4`. O extra opcional `linear_ration_highs` instala PuLP e `highspy` para o piloto. |

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

O backend padrão é SLSQP. PuLP atende **NRC, LAC_COW e formulação automática**. Os demais grupos e modalidades mantêm o fluxo original, com dieta direta para CALF. A produção tenta a dieta anterior compatível primeiro e depois os quatro objetivos básicos na ordem listada. `single` usa a primeira referência utilizável, `full` explora até o orçamento e `adaptive_gap` pode parar ao atingir a meta. Ao esgotar o orçamento, retorna a melhor dieta aprovada disponível. A Midwest está disponível por configuração opcional, com ordem dependente do orçamento.

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

## Piloto HiGHS na CLI concluído

HiGHS é o solver nutricional priorizado para o método linear em avaliação, selecionado por `animal.ration.linear_nutritional_solver = "highs"` com o extra `linear_ration_highs`. A configuração padrão do backend linear é CBC, e o padrão do motor é SLSQP. CBC continua nas referências e no limite inferior neste piloto. A regressão das 552 matrizes reproduziu 168 aprovações finais em CBC e 223 em HiGHS. As suítes relacionadas tiveram 663 testes aprovados.

Na CLI de três dias com as entradas arquivadas, HiGHS full e adaptive_gap concluíram os dias 150–152 com US$ 88,86 de alimento aplicado na lactação, frente a US$ 504,56 com CBC e US$ 88,23 com SLSQP. No último dia, o custo formulado foi US$ 0,369657/vaca no HiGHS frente a US$ 5,691552 no CBC. Os cenários completos produziram 9.659,51 kg de leite. Single manteve as dietas de CBC e encerrou após dois dias completos por exceder o teto de PM no terceiro. As oito dietas aprovadas no HiGHS foram aplicadas exatamente por ID. Nenhum gap atingiu 5%.

Nos 132 casos pareados por hash de matriz, as aprovações subiram de 19 para 29 e as rejeições brutas com causa numérica caíram de 33 para zero. Permaneceram 72 casos com rejeição bruta por aproximação. Nas trajetórias full e adaptive_gap, as exigências já divergiam no terceiro dia. O benchmark arquivado, com matrizes fixas do CBC, aprovou US$ 0,369587/vaca nesse mesmo dia. A fase nutricional ficou mais rápida nas três estratégias, e a duração total da CLI teve resultados mistos. A geração de referências consumiu cerca de 86% a 87% do tempo de otimização em full e adaptive_gap no HiGHS.

[Relatório da CLI com HiGHS](helpful_scripts/nrc_ration_comparison/cli_highs_three_day_report.md) e [comparação detalhada](output/nrc_cli_three_day_highs/comparison.json). O diretório novo preserva insumos, manifesto, logs e capturas por fase. Os cenários anteriores permanecem nos diretórios históricos.

## Piloto isolado de HiGHS nas referências concluído

Foram comparados CBC e HiGHS na geração dos quatro objetivos em 12 cenários estáticos e 15 tentativas reconstruídas, com cinco repetições e HiGHS nos casos nutricionais em ambos os braços. CBC calculou o limite. A mediana por formulação caiu de **818 para 49 ms** na geração e de **966 para 179 ms** no adaptador completo. Ambos aprovaram **27/27 formulações**. As aprovações finais por regime passaram de **261 para 268** e 3/27 para 4/27 atingiram gap de 5%. Os custos nas 15 tentativas da CLI coincidiram a US$ 1e-9.

HiGHS gerou 107 referências compatíveis, todas dentro das oito tolerâncias básicas, e encontrou uma inviabilidade no sexto estágio da meta de MS. CBC gerou 108 referências, das quais duas foram rejeitadas por limites individuais. Ambos descartaram duas duplicatas. Entre os cenários estáticos, o maior ganho de custo foi US$ 0,212580/vaca/dia. A perda da referência no desempate elevou o melhor custo de outro cenário em US$ 0,003197/vaca/dia. O ponto deve entrar na regressão de uma eventual promoção do gerador.

O diagnóstico isolado dos duais HiGHS encontrou 216 multiplicadores presentes e com sinal admissível. Os certificados tolerantes ficaram a até 7,11e-15 US$/vaca/dia do ótimo da relaxação tolerante explícita. A configuração de produção e o limite usado para os gaps continuam com CBC nas etapas auxiliares. [Relatório do piloto](helpful_scripts/nrc_ration_comparison/reference_solver_pilot_report.md) e [resultados detalhados](output/nrc_reference_solver_pilot/results.json).

## Seleção do gerador HiGHS no fluxo de produção

A configuração `animal.ration.linear_reference_solver` aceita `cbc` (padrão) ou `highs`, independentemente do solver dos LPs nutricionais. O extra `linear_ration_highs` fornece a dependência. A Pen registra o solver em `reference_solver`. Com HiGHS indisponível, a inicialização gera erro explícito. CBC é utilizado no cálculo do limite inferior em produção.

A [regressão do sexto desempate](tests/test_biophysical/test_animal/test_ration/test_lexicographic_highs_regression.py) reproduz os coeficientes, limites, RHS e objetivo arquivados. O certificado racional prova que a matriz congelada é inviável: a combinação do piso de fósforo com os bloqueios de custo e dos ingredientes 44 e 50 exige um valor acima do máximo sobre a caixa em 2,59e-9 na escala do certificado. O estágio anterior carregava um déficit de fósforo de 4,64e-8 g, aceito numericamente pelo solver. Com o bloqueio seguinte, essa imprecisão se tornou uma incompatibilidade efetiva. As tolerâncias NRC, a folga dos bloqueios e a política de falhas foram preservadas.

Em busca `full` com orçamentos de 1, 2, 3 e 5 referências, ambos os geradores aprovaram 21, 27, 27 e 27 das mesmas 27 formulações arquivadas. No caso crítico, o estágio de meta de MS foi alcançado apenas com orçamento 5. A falha de geração foi registrada e a busca HiGHS manteve a dieta aprovada de US$ 3,904341/vaca/dia. O CBC aprovou US$ 3,901144 ao atingir a meta de MS. [Resultados por orçamento](output/nrc_reference_solver_budgets/results.json).

A [regressão do limite](helpful_scripts/nrc_ration_comparison/test_cost_bound_solver_regression.py) comparou os ótimos primais, os sinais e complementaridade, e o resíduo de estacionariedade `c − Aᵀπ − dj` nas 27 relaxações. A maior diferença primal foi 9,45e-8 US$/vaca/dia. Os maiores resíduos absolutos de estacionariedade foram 4,46e-9 para CBC e 2,78e-17 para HiGHS. O ensaio sintético também verificou os dois sinais para desigualdades ativas.

## HiGHS configurável nas três etapas e CLI replicada

O método linear permite selecionar `cbc` ou `highs` de forma independente em `animal.ration.linear_reference_solver`, `linear_bound_solver` e `linear_nutritional_solver`. Os três usam CBC por padrão. SLSQP é o backend padrão do RuFaS. A Pen expõe os nomes dos três solvers usados. O certificado inferior continua usando duais válidos, minimização da estacionariedade na caixa e a relaxação induzida pelas tolerâncias NRC. O ótimo primal é apenas um teto adicional para o certificado. A suíte de regressão teve **686 testes aprovados**.

Foram concluídas **35 simulações de três dias**, cinco por configuração, com os mesmos insumos e a mesma instrumentação. Em `full`, o tempo mediano de otimização da lactação passou de **7,467 s** com CBC e **4,376 s** com HiGHS nutricional para **0,608 s** com HiGHS integral. As medianas da CLI foram **40,80 s**, **31,62 s** e **29,67 s**. O custo de lactação aplicado com HiGHS integral foi US$ **88,86** em `full` e US$ **88,86** em `adaptive_gap`. Os gaps de adaptive_gap foram 23,82%, 32,11%, 25,37%. As dietas lineares aplicadas coincidiram por ID com as dietas aprovadas e reportadas.

O próximo estudo recomendado é o de referências independentes, com o solver fixo e entradas comparáveis. A duração maior fica para a validação da estratégia após esse estudo. [Relatório replicado](helpful_scripts/nrc_ration_comparison/cli_solver_consolidation_report.md) e [dados de comparação](output/nrc_solver_consolidation/comparison.json).

## Referências regionais independentes avaliadas

O ensaio isolado usou HiGHS nas três etapas em 12 cenários estáticos e 15 tentativas reconstruídas. Nenhuma receita regional inteira coube nos cardápios. As projeções preservaram 71,52% de Midwest, 27,48% de Northeast, 19,71% de Southwest e 16,99% de Intermountain. Southwest e Intermountain se tornaram o mesmo vetor. Todas as políticas aprovaram 27/27 formulações. Em busca completa, A/B/C tiveram 268/337/387 casos aprovados e nenhuma rejeição bruta classificada como numérica. Midwest reduziu o melhor custo em dois cenários, em até US$ 0,379336/vaca/dia. As demais projeções não melhoraram o melhor custo completo.

Para orçamento 2 ou 3, o resultado favorece Midwest após a dieta anterior quando disponível e após menor custo. Para orçamento 5, o resultado favorece a ordem atual e Midwest quando sobrar uma vaga. A promoção depende de autorização. [Relatório](helpful_scripts/nrc_ration_comparison/independent_reference_experiment_report.md) e [resultados detalhados](output/nrc_independent_references/results.json).

## Midwest opcional no fluxo de produção

A configuração `animal.ration.linear_midwest_reference_path` recebe um caminho relativo, a partir do diretório de execução, para um JSON de alimentação RuFaS com uma receita de lactação explícita. Omitir o campo ou deixá-lo vazio desabilita a opção. É possível usar `input/data/feed/example_Midwest_feed.json` ou um arquivo Midwest próprio. O adaptador carrega a receita configurada uma vez e calcula a projeção por tentativa com os IDs do cardápio NRC e a meta inicial de MS. A certificação final continua usando as 14 restrições originais. No exemplo arquivado, os IDs 301 e 302 foram removidos e a participação retida foi 71,52%.

Com orçamento de duas ou três referências, a Midwest é inserida após menor custo, precedido da dieta anterior quando disponível. Com cinco, ela entra ao final da ordem anterior caso sobre vaga. Em `single`, a ordem das fontes atuais tem precedência e permanece o orçamento de uma referência distinta. `adaptive_gap` pode parar antes da Midwest. A Pen registra o caminho, o grupo, os ingredientes removidos, a participação retida, as proporções normalizadas, incompatibilidades e duplicatas, as referências tentadas e a vencedora.

A regressão de produção reproduziu as 27 formulações em seis combinações de configuração e orçamento com HiGHS nas três etapas. Todos os braços aprovaram 27/27. As chamadas passaram de 675 para 549 com orçamento 2, de 1.062 para 837 com orçamento 3 e de 1.595 para 1.691 com orçamento 5. Midwest reduziu o melhor custo em três, três e duas formulações, respectivamente. As maiores economias foram US$ 0,647575, US$ 0,379336 e US$ 0,379336/vaca/dia, sem aumento observado nesses braços. Por formulação, foram verificados o limite, gap, referência vencedora, dietas, contagens e status dos regimes. O teste com `HerdManager` e Pen confirmou que a aplicação corresponde exatamente à dieta certificada.

A suíte relacionada terminou com **713 testes aprovados**. [Regressão das 27 formulações](helpful_scripts/nrc_ration_comparison/test_midwest_reference_regression.py). Uma nova simulação longitudinal aguarda autorização.

## Simulação exploratória de 30 dias concluída

Uma repetição por cenário concluiu os dias 150–179 de 2013 no cenário NRC `animals_only`, com os insumos arquivados e semente 42. SLSQP, HiGHS full com 3 referências e HiGHS full com 5 referências completaram 30 reformulações de lactação cada, com zero rejeições de formulação. Os dois braços HiGHS usaram Midwest e HiGHS nas três etapas. Os custos totais aplicados foram US$ 1.226,76, US$ 1.256,07 e US$ 1.248,65. O leite acumulado foi 98.923,12, 99.814,17 e 99.814,17 kg. Os tempos de otimização da lactação foram 3,26, 5,33 e 10,38 s. Os três processos foram cronometrados em paralelo para atender ao prazo da apresentação.

A Midwest foi explorada em 30 dias com orçamento 3 e em um dia com orçamento 5. Ela não venceu em nenhum. Os gaps medianos foram 24,18% e 24,19%, e nenhum gap atingiu 5%. As dietas aprovadas pelos braços lineares foram aplicadas por ID. As exigências diferiram após o dia inicial na comparação com SLSQP. Os acumulados são comparações descritivas entre trajetórias, com uma semente e preços ilustrativos.

[Relatório para apresentação](helpful_scripts/nrc_ration_comparison/cli_midwest_30day_report.md), [séries diárias](output/nrc_midwest_30day/daily_metrics.csv) e [tabela de métricas](output/nrc_midwest_30day/summary.csv). Trabalhos futuros incluem generalização das referências externas, geração dinâmica de referências e sensibilidade às variações de preços.

## Sensibilidade estática a preços e disponibilidade

No cenário arquivado `114502_midwest_plus_soy_market`, foram comparadas 44 variantes estáticas de preço, retirada e teto de inclusão. SLSQP e HiGHS full com cinco referências aprovaram 44/44, enquanto HiGHS full com três aprovou 43/44. Todos os braços lineares usaram HiGHS nas três etapas e Midwest habilitada. A única ausência de candidata aprovada ocorreu ao retirar o milho em grão, com a relaxação básica viável e dietas certificadas pelos outros dois métodos. O teto da silagem de milho, ao cair 50% do máximo efetivo, elevou o custo encontrado pelo HiGHS em 6,37%. O cenário com corte e aumento de preço mostrou que uma dieta mais barata obtida em outra busca ainda era admissível. O resultado delimita o efeito da seleção de referências sobre a qualidade econômica.

[Relatório de sensibilidade](helpful_scripts/nrc_ration_comparison/static_price_availability_report.md), [custos e gaps](output/nrc_price_availability_sensitivity/summary.csv) e [composição por ingrediente](output/nrc_price_availability_sensitivity/composition.csv). O ensaio usou apenas formulações estáticas e a implementação de produção existente.

## Próximas etapas, por prioridade

1. **Preservar os arquivos e artefatos do workspace** antes de trocar de checkout. Registrar a revisão exata dos próximos experimentos. Usar os resultados arquivados para iniciar o trabalho.
2. **Retomar a investigação nutricional quando autorizado.** Avaliar generalização de referências externas, geração dinâmica e sensibilidade a preços. Para medir o efeito isolado da Midwest, manter um controle longitudinal com a opção desabilitada.
3. **Adicionar uma opção de referência independente compatível.** Definir projeção da receita, orçamento e gatilho para explorar a alternativa. Usar Midwest como exemplo, manter ingredientes e preços fixos e testar o efeito com o mesmo solver. A solução SLSQP permanece exclusivamente diagnóstica.
4. **Tratar separadamente a exceção da Pen e a possível reutilização.** Exercitar o limite de redução de leite e revalidar dieta anterior diante das exigências correntes. Distinguir falha computacional, ausência de candidata e dieta anterior fora das restrições.
5. **Ampliar os cenários gradualmente após os pilotos isolados.** Medir tempo integral, custo, leite, consumo, referências, gaps e falhas. Investigar preços mais representativos e relaxações comprovadas que fortaleçam o limite. Preservar os coeficientes fixos e a certificação original.

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

## Estado do Git e preservação

No encerramento para a apresentação, a branch era `feature/pulp-optimizer` no commit `f025c79be`, com zero commits de diferença em relação à referência local `origin/feature/pulp-optimizer`. As alterações do projeto estão na árvore de trabalho. O índice Git estava vazio. A referência remota local foi consultada sem atualizar o remoto.

### O que versionar

A lista nominal em [inventário de versionamento](helpful_scripts/nrc_ration_comparison/reproduction/version_files.tsv) reúne as alterações do ciclo após `f025c79be`. Inclui código de produção, schema e dependências declaradas, testes e a matriz de regressão do sexto desempate, roteiros e relatórios experimentais, e as duas tabelas compactas de 30 dias para a apresentação. Os scripts históricos já versionados e suas entradas de regressão permanecem no histórico.

### O que preservar fora do Git

O arquivo [manifesto dos artefatos](helpful_scripts/nrc_ration_comparison/reproduction/artifacts_local.tsv) registra tamanhos e SHA-256 para insumos congelados e resultados que permitem reproduzir e auditar os ensaios. Preserve esses arquivos sob os caminhos indicados em um arquivo externo ou no workspace. Os testes das 552 matrizes e das 27 formulações usam artefatos em `output/` e podem pular a verificação em um checkout limpo sem essas entradas. O manifesto é um inventário verificável do material local.

Mantenha `output/`, logs brutos por execução, bibliotecas instaladas em `output/nrc_solver_benchmark/deps/`, ambientes virtuais, caches e bytecode fora dos commits. A declaração da dependência fica em `pyproject.toml`. Os JSONs históricos já versionados em `f025c79be` não precisam ser adicionados novamente. `adaptive_results.json` é lido pelo carregador de cenários, portanto deve permanecer disponível.

### Reprodução dos ensaios consolidados

Use Python 3.12 e instale `.[linear_ration_highs]`. As execuções mais recentes usaram Python 3.12.10, PuLP 3.3.2, highspy 1.16.0 e CBC 2.10.3. No workspace do experimento, highspy estava em um diretório local no `PYTHONPATH`. Em outra máquina, o extra permite instalar a biblioteca no ambiente. Para comparação estrita, fixe as versões registradas.

| Etapa | Roteiro ou entrada |
|---|---|
| CLI e auditoria de três dias | `cli_three_day.py`, `cli_three_day_trace.py`, `cli_three_day_summary.py` e `cli_isolated_audit.py`. Os caminhos e comandos constam na seção de reprodução. |
| Benchmark de 552 matrizes e limite | `solver_benchmark.py` e `reference_solver_pilot.py`, com as entradas arquivadas em `output/nrc_cli_three_day/`. |
| Consolidação de sete cenários, cinco repetições | `py -3.12 -m helpful_scripts.nrc_ration_comparison.cli_solver_consolidation --runs 5 --output output/nrc_solver_consolidation_repro` |
| Referências independentes | `py -3.12 -m helpful_scripts.nrc_ration_comparison.independent_reference_experiment --runs 3 --output output/nrc_independent_references_repro` |
| Trajetória de 30 dias | [Cópias dos roteiros de execução e análise](helpful_scripts/nrc_ration_comparison/reproduction/README.md). A tabela de apresentação e as séries diárias foram copiadas sem alterações. |

Os comandos são registrados para retomada futura. A implementação e os experimentos ficam pausados para a apresentação.

## Relatório comparativo independente de 30 dias

O [gerador comparativo](helpful_scripts/nrc_ration_comparison/comparison_report.py) lê exportações explícitas e os metadados dos cadastros. A [documentação](helpful_scripts/nrc_ration_comparison/comparison_report.md) registra o comando, a estrutura dos CSVs, as regras de agregação e a auditoria nutricional. O [relatório local](output/nrc_comparison_report_30day_final/index.html) reúne HTML autocontido, 12 CSVs, 22 PNGs e o manifesto de proveniência. As simulações e os artefatos históricos foram preservados.

| Execução | Custo acumulado fornecido (US$) | MS fornecida (kg) | Leite (kg) | US$/kg de leite |
|---|---:|---:|---:|---:|
| SLSQP | 1.226,76 | 104.501,78 | 98.923,12 | 0,012401 |
| HiGHS, três referências | 1.256,07 | 105.120,64 | 99.814,17 | 0,012584 |
| HiGHS, cinco referências, manual | 1.248,65 | 105.120,64 | 99.814,17 | 0,012510 |

Aos preços ilustrativos efetivamente usados, os custos do HiGHS ficaram 2,39% e 1,78% acima do SLSQP. O braço de cinco referências ficou 0,59% abaixo do de três. Houve 30 tentativas bem-sucedidas de lactação por execução, com aprovação NRC linear em 30/30 em cada braço HiGHS. Os gaps medianos foram 24,18% e 24,19%. São trajetórias descritivas com uma semente e diferenças nas exigências e no leite.

A execução manual das 15h56 contém todos os dias de simulação de 0 a 29, inclusive 8 e 15. A primeira dieta de lactação oferece 33,637059 kg MS/animal/dia para a meta de 25,87466075 kg. O limite NRC superior é 33,63705898 kg, com tolerância linear absoluta de 10⁻⁷ kg. O excedente de arredondamento de aproximadamente 2,04 × 10⁻⁸ kg fica dentro dessa tolerância. O relatório mostra os resíduos das 14 restrições para essa dieta e os indicadores originais do reporter em colunas distintas.

Custos de aquisição efetiva estão indisponíveis nos JSONs comparados. Os logs e rastreamentos instrumentados de cinco referências pertencem à execução anterior e ficaram fora da auditoria da exportação manual. Os cinco testes do gerador passaram. Foram verificados os 270 registros de tentativa exportados, as 90 linhas diárias do rebanho, as 360 linhas de lote e a identidade dos 22 PNGs incorporados no HTML com os arquivos individuais.

### Versão resumida para consulta

A [página resumida](output/nrc_comparison_report_30day_summary/index.html) usa os mesmos resultados e apresenta cinco gráficos, uma tabela executiva e seleção local de dia e lote. A [página técnica](output/nrc_comparison_report_30day_summary/detailed_report.html) contém a auditoria integral. Os links da página resumida dão acesso aos 12 CSVs e aos 22 PNGs independentes. A geração foi feita em um diretório novo, a partir das exportações existentes.

## CLI experimental instalada

`rufas-linear` e `rufas-compare` compartilham os preparadores versionados do piloto NRC e invocam `RUFAS.main` em subprocesso por braço. O ponto de entrada original `rufas = "RUFAS.main:main"` permanece registrado. O padrão usa três dias, semente 42, cinco referências, Midwest habilitada e HiGHS nas três etapas. Cada execução grava entradas e diagnósticos em um diretório novo. O README documenta opções, instalação e escopo experimental.

A validação do resumo em terminal sobre os resultados arquivados de 30 dias reproduziu os custos de US$ 1.226,76, US$ 1.256,07 e US$ 1.248,65. As únicas novas simulações cobriram três dias por braço.

| Comando de validação | Custo fornecido | Leite | Tentativas com sucesso | Aprovação nutricional em lactação |
|---|---:|---:|---:|---|
| `rufas-compare --days 3 --html` · SLSQP | US$ 121,43 | 9.659,51 kg | 9/9 | 0/3 no avaliador legado |
| `rufas-compare --days 3 --html` · HiGHS, cinco referências | US$ 122,66 | 9.659,51 kg | 9/9 | 3/3 pela validação NRC linear |
| `rufas-linear --days 3 --references 3` | US$ 124,50 | 9.659,51 kg | 9/9 | 3/3 pela validação NRC linear |

A [comparação integrada](output/ration_cli_short_validation/compare-20261124-173606-d554466d8788/report/index.html) gerou as duas páginas HTML. A [execução linear com três referências](output/ration_cli_short_validation/linear-20261124-173848-475fd9bbfdc6/terminal_summary.json) gerou resumo e CSVs. Os artefatos históricos de 30 dias foram preservados.
