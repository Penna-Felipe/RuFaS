# Consolidação de HiGHS no cenário NRC de três dias

Foram executadas 35 simulações sequenciais com os insumos arquivados de `animals_only` freestall, população inicial arquivada, semente 42, dias julianos 150–152 de 2013 e reformulação diária. Foram cinco repetições por configuração, com rotação da ordem e mesma instrumentação na CLI. Cada repetição iniciou um processo Python novo. O orçamento dos métodos lineares foi de cinco referências, com meta de gap de 5%. Os resultados sem tempo foram idênticos entre as cinco repetições de cada configuração, considerando dias, totais por grupo, tentativas, dietas, requisitos registrados e contagens NRC. O manifesto registra o código e as entradas.

Ambiente medido com Python 3.12.10, PuLP 3.3.2, highspy 1.16.0 e CBC 2.10.3. Neste relatório, HiGHS nutricional usa CBC na geração e no limite. HiGHS integral usa HiGHS nas três etapas.

## Resultados acumulados e tempo integral

O custo representa alimentação aplicada aos preços de entrada, em US$. A coluna de casos lineares apresenta aprovados, rejeitados pelo NRC, inviáveis e aprovações após reparo. Para SLSQP, os números de NRC são uma checagem diagnóstica do vetor aplicado. Os tempos são medianas de cinco repetições. A otimização soma as tentativas da baia de lactação. O tempo da CLI inclui inicialização e emissão dos relatórios.

| Cenário | Dias | Tentativas bem-sucedidas | Casos NRC | Custo lactação, US$ | Leite, kg | MS lactação, kg | Otimização, s | CLI, s |
|---|---|---|---|---|---|---|---|---|
| SLSQP | 3 | 3/3 | diagnóstico NRC: 0 / 3 | 88,23 | 9.659,51 | 7.795,49 | 0,665 | 30,55 |
| CBC full | 3 | 3/3 | 11 / 67 / 6 / 5 | 504,56 | 9.659,51 | 7.795,49 | 7,467 | 40,80 |
| CBC adaptive_gap | 3 | 3/3 | 11 / 67 / 6 / 5 | 504,56 | 9.659,51 | 7.795,49 | 7,131 | 40,84 |
| HiGHS nutricional full | 3 | 3/3 | 21 / 57 / 6 / 10 | 88,86 | 9.659,51 | 7.795,49 | 4,376 | 31,62 |
| HiGHS nutricional adaptive_gap | 3 | 3/3 | 21 / 57 / 6 / 10 | 88,86 | 9.659,51 | 7.795,49 | 4,994 | 35,54 |
| HiGHS integral full | 3 | 3/3 | 21 / 57 / 6 / 11 | 88,86 | 9.659,51 | 7.795,49 | 0,608 | 29,67 |
| HiGHS integral adaptive_gap | 3 | 3/3 | 21 / 57 / 6 / 11 | 88,86 | 9.659,51 | 7.795,49 | 0,686 | 31,94 |

Custo acumulado por grupo em US$.

| Cenário | CALF | GROWING | CLOSE_UP | LAC_COW |
|---|---|---|---|---|
| SLSQP | 7,80 | 18,33 | 7,07 | 88,23 |
| CBC full | 8,40 | 18,33 | 7,07 | 504,56 |
| CBC adaptive_gap | 8,40 | 18,33 | 7,07 | 504,56 |
| HiGHS nutricional full | 8,40 | 18,33 | 7,07 | 88,86 |
| HiGHS nutricional adaptive_gap | 8,40 | 18,33 | 7,07 | 88,86 |
| HiGHS integral full | 8,40 | 18,33 | 7,07 | 88,86 |
| HiGHS integral adaptive_gap | 8,40 | 18,33 | 7,07 | 88,86 |

## Tempos por etapa

A parte nutricional é medida a partir dos seis LPs por referência. O tempo de reparo é parte do tempo medido de validação e reparo. Montagem, administração da busca e outras despesas do adaptador entram no tempo total da otimização.

| Cenário | Referências, s | Limite, s | LPs nutricionais, s | Validação e reparo, s | Reparo, s | CLI mín.–máx., s |
|---|---|---|---|---|---|---|
| SLSQP | — | — | — | — | — | 27,55–35,34 |
| CBC full | 3,625 | 0,141 | 3,329 | 0,198 | 0,062 | 38,27–44,25 |
| CBC adaptive_gap | 3,628 | 0,103 | 3,057 | 0,169 | 0,055 | 35,37–41,82 |
| HiGHS nutricional full | 3,658 | 0,096 | 0,229 | 0,205 | 0,104 | 27,18–36,93 |
| HiGHS nutricional adaptive_gap | 3,978 | 0,138 | 0,183 | 0,237 | 0,107 | 25,82–45,65 |
| HiGHS integral full | 0,179 | 0,016 | 0,133 | 0,168 | 0,079 | 24,87–47,21 |
| HiGHS integral adaptive_gap | 0,177 | 0,016 | 0,157 | 0,195 | 0,097 | 26,03–35,62 |

Em `full`, a otimização caiu de 4,376 s com HiGHS nutricional e 7,467 s com CBC para 0,608 s com HiGHS integral. A CLI registrou medianas de 31,62 s, 40,80 s e 29,67 s, respectivamente. As fases são medidas diretamente nos seus pontos de chamada e as medianas das fases são calculadas separadamente.

## Dia a dia na lactação

| Cenário | Dia | Dieta, US$/vaca | Aplicado, US$ | MS, kg/vaca | Leite, kg | Limite, US$/vaca | Gap | Referências | Chamadas | Escolhida |
|---|---|---|---|---|---|---|---|---|---|---|
| SLSQP | 150 | 0,366303 | 28,21 | 33,637058 | 3.202,69 | — | — | — | — | — |
| SLSQP | 151 | 0,405576 | 31,63 | 33,455753 | 3.228,72 | — | — | — | — | — |
| SLSQP | 152 | 0,363991 | 28,39 | 33,280573 | 3.228,10 | — | — | — | — | — |
| CBC full | 150 | 0,373645 | 28,77 | 33,637059 | 3.202,69 | 0,278794 | 25,39% | 4 | 60 | minimum_cost |
| CBC full | 151 | 0,408320 | 31,85 | 33,455753 | 3.228,72 | 0,277202 | 32,11% | 5 | 66 | target_dmi |
| CBC full | 152 | 5,691552 | 443,94 | 33,280572 | 3.228,10 | 0,275871 | 95,15% | 5 | 66 | previous_ration |
| CBC adaptive_gap | 150 | 0,373645 | 28,77 | 33,637059 | 3.202,69 | 0,278794 | 25,39% | 4 | 60 | minimum_cost |
| CBC adaptive_gap | 151 | 0,408320 | 31,85 | 33,455753 | 3.228,72 | 0,277202 | 32,11% | 5 | 66 | target_dmi |
| CBC adaptive_gap | 152 | 5,691552 | 443,94 | 33,280572 | 3.228,10 | 0,275871 | 95,15% | 5 | 66 | previous_ration |
| HiGHS nutricional full | 150 | 0,365979 | 28,18 | 33,637059 | 3.202,69 | 0,278794 | 23,82% | 4 | 60 | target_dmi |
| HiGHS nutricional full | 151 | 0,408320 | 31,85 | 33,455753 | 3.228,72 | 0,277202 | 32,11% | 5 | 66 | target_dmi |
| HiGHS nutricional full | 152 | 0,369657 | 28,83 | 33,280572 | 3.228,10 | 0,275871 | 25,37% | 5 | 66 | target_dmi |
| HiGHS nutricional adaptive_gap | 150 | 0,365979 | 28,18 | 33,637059 | 3.202,69 | 0,278794 | 23,82% | 4 | 60 | target_dmi |
| HiGHS nutricional adaptive_gap | 151 | 0,408320 | 31,85 | 33,455753 | 3.228,72 | 0,277202 | 32,11% | 5 | 66 | target_dmi |
| HiGHS nutricional adaptive_gap | 152 | 0,369657 | 28,83 | 33,280572 | 3.228,10 | 0,275871 | 25,37% | 5 | 66 | target_dmi |
| HiGHS integral full | 150 | 0,365979 | 28,18 | 33,637059 | 3.202,69 | 0,278794 | 23,82% | 4 | 60 | target_dmi |
| HiGHS integral full | 151 | 0,408320 | 31,85 | 33,455753 | 3.228,72 | 0,277202 | 32,11% | 5 | 66 | target_dmi |
| HiGHS integral full | 152 | 0,369657 | 28,83 | 33,280572 | 3.228,10 | 0,275872 | 25,37% | 5 | 66 | target_dmi |
| HiGHS integral adaptive_gap | 150 | 0,365979 | 28,18 | 33,637059 | 3.202,69 | 0,278794 | 23,82% | 4 | 60 | target_dmi |
| HiGHS integral adaptive_gap | 151 | 0,408320 | 31,85 | 33,455753 | 3.228,72 | 0,277202 | 32,11% | 5 | 66 | target_dmi |
| HiGHS integral adaptive_gap | 152 | 0,369657 | 28,83 | 33,280572 | 3.228,10 | 0,275872 | 25,37% | 5 | 66 | target_dmi |

Dias com exigências, dieta anterior e ordem de ingredientes idênticas na comparação HiGHS nutricional e HiGHS integral por estratégia. full nos dias 150, 151, 152 / adaptive_gap nos dias 150, 151, 152. Os totais da CLI com solvers distintos descrevem trajetórias. Os cenários compartilham as entradas iniciais, e a dieta aplicada pode alterar as exigências dos dias seguintes.

HiGHS integral e HiGHS nutricional aplicaram as mesmas dietas por ID nos três dias em ambas as estratégias. O limite integral ficou cerca de US$ 4,52e-7/vaca/dia acima do limite CBC. A meta de 5% ficou fora do alcance. Full e adaptive_gap com HiGHS integral custaram, respectivamente, US$ 88,86 e US$ 88,86 na lactação. Os stops de adaptive_gap foram references_exhausted, reference_limit, reference_limit. A instrumentação verificou que toda dieta linear selecionada correspondeu exatamente à aprovada pelo NRC, à aplicada pela Pen e à reportada por ID. As checagens das etapas também verificaram os nomes dos solvers e as contagens de LPs.

## Certificado e configuração

O limite continua sendo calculado na relaxação original com oito restrições básicas. Multiplicadores ausentes, inválidos ou com sinais incorretos contribuem zero. Os resíduos de estacionariedade são minimizados na caixa de ingredientes. O ótimo primal apenas limita superiormente o valor reportado do certificado. O tratamento do objetivo identicamente nulo ignora a coluna auxiliar de coeficiente zero criada pelo PuLP. As regressões cobriram a degenerescência, custo nulo, limites ativos, inviabilidade, sinais, estacionariedade, parada por gap e o sexto desempate lexicográfico. A suíte relacionada teve 686 testes aprovados.

Instale o extra `linear_ration_highs` e use o seguinte bloco em `animal.ration`.

```json
{
  "user_input": false,
  "optimizer_backend": "pulp",
  "linear_reference_solver": "highs",
  "linear_bound_solver": "highs",
  "linear_nutritional_solver": "highs",
  "linear_strategy": "adaptive_gap",
  "linear_gap_target": 0.05,
  "linear_max_references": 5,
  "formulation_interval": 1
}
```

As três opções aceitam `cbc` e `highs` de forma independente. CBC é o padrão de cada etapa linear, e SLSQP é o backend padrão do RuFaS. A solicitação de HiGHS indisponível emite erro explícito.

O próximo estudo recomendado é o de referências independentes. O solver já reduziu substancialmente o custo computacional, enquanto a escolha de referência e a aproximação nutricional ainda determinam quais dietas são encontradas. Uma simulação longa é mais informativa depois que uma referência independente for avaliada sob as mesmas exigências e o mesmo solver.

## Artefatos

`output/nrc_solver_consolidation/comparison.json` contém resultados por grupo e dia, dietas por ID, ofertas e exigências, casos NRC, referências, limites e as cinco medições por configuração. Os subdiretórios de cada repetição preservam os JSONs da CLI, console, `attempts.jsonl` e `phases.jsonl`. O [roteiro](cli_solver_consolidation.py) reproduz o ensaio em um diretório de saída novo:

```powershell
py -3.12 -m helpful_scripts.nrc_ration_comparison.cli_solver_consolidation --runs 5 --output output/nrc_solver_consolidation_repro
```
