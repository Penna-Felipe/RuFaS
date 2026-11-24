# Piloto PuLP/HiGHS na CLI de três dias

Executado em 24 de novembro de 2026, no HEAD `f025c79be` com as alterações locais do piloto registradas no manifesto. Foram copiadas as entradas arquivadas de `animals_only` freestall, dias julianos 150–152 de 2013, semente 42, padrão NRC e reformulação diária. A população, a tabela NRC e os demais arquivos de entrada usam os mesmos caminhos do cenário arquivado. Cada configuração recebeu `linear_nutritional_solver: highs` em `animal.ration`. Foi usado Python 3.12.10, PuLP 3.3.2, highspy 1.16.0 e CBC 2.10.3. CBC resolveu a geração de referências e o limite de custo. O fluxo original continuou atendendo os demais grupos.

## Sete trajetórias

Custo aplicado é a matéria seca fornecida à baia, valorizada aos preços de entrada, em US$. Totais incluem os dias completos. A duração total mede a CLI, incluindo inicialização e saídas. Otimização mede a soma das tentativas de lactação, inclusive as rejeitadas. As execuções HiGHS incluem instrumentação de diagnóstico.

| Cenário | Dias | Custo lactação | Custo demais grupos (CALF / GROWING / CLOSE_UP) | MS lactação, kg | Leite, kg | Otimização, s | CLI, s |
|---|---:|---:|---:|---:|---:|---:|---:|
| SLSQP | 3 | 88,23 | 7,80 / 18,33 / 7,07 | 7.795,49 | 9.659,51 | 0,79 | 37,57 |
| CBC single | 2 | 440,18 | 5,70 / 10,90 / 4,42 | 5.199,60 | 6.412,15 | 1,91 | 33,42 |
| CBC full | 3 | 504,56 | 8,40 / 18,33 / 7,07 | 7.795,49 | 9.659,51 | 14,02 | 47,84 |
| CBC adaptive_gap | 3 | 504,56 | 8,40 / 18,33 / 7,07 | 7.795,49 | 9.659,51 | 5,08 | 29,55 |
| HiGHS single | 2 | 440,18 | 5,70 / 10,90 / 4,42 | 5.199,60 | 6.412,15 | 1,03 | 39,79 |
| HiGHS full | 3 | 88,86 | 8,40 / 18,33 / 7,07 | 7.795,49 | 9.659,51 | 5,23 | 38,30 |
| HiGHS adaptive_gap | 3 | 88,86 | 8,40 / 18,33 / 7,07 | 7.795,49 | 9.659,51 | 4,13 | 33,43 |

| Trajetória | Dias | Custo formulado, US$/vaca/dia | Custo aplicado por dia, US$ | MS, kg/vaca/dia |
|---|---|---|---|---|
| SLSQP | 150–152 | 0,366303 / 0,405576 / 0,363991 | 28,205 / 31,635 / 28,391 | 33,637058 / 33,455753 / 33,280573 |
| CBC e HiGHS single | 150–151 | 0,373645 / 5,274511 | 28,771 / 411,412 | 33,637059 / 33,455753 |
| CBC full e adaptive_gap | 150–152 | 0,373645 / 0,408320 / 5,691552 | 28,771 / 31,849 / 443,941 | 33,637059 / 33,455753 / 33,280572 |
| HiGHS full e adaptive_gap | 150–152 | 0,365979 / 0,408320 / 0,369657 | 28,180 / 31,849 / 28,833 | 33,637059 / 33,455753 / 33,280572 |

Em HiGHS full e adaptive_gap, a dieta de lactação do dia 150 usou os IDs 23, 50 e 110 a 0,328981, 6,858594 e 26,449484 kg MS/vaca. No dia 151, os dois solvers aplicaram a mesma dieta, a 0,819583, 8,773057 e 23,863113 kg MS/vaca. No dia 152, HiGHS selecionou 0,409458, 7,118681 e 25,752433 kg MS/vaca desses mesmos IDs. A dieta de CBC do dia 152 usou os IDs 44, 50, 167 e 231 a 6,004282, 20,683489, 6,404803 e 0,187998 kg MS/vaca. Nesse último dia, PM exigida/ofertada na média da Pen foi 2.861,37/2.907,24 g com HiGHS, 2.860,91/4.058,73 g com CBC e 2.867,62/2.869,37 g com SLSQP. A oferta reportada agrega o cálculo individual, enquanto a aprovação usa o RationConfig da baia.

## Rejeições, reparos e comparação controlada

| Cenário linear | Tentativas aprovadas / totais | Casos aprovados / rejeitados NRC / inviáveis | Busca de reparo / reparos aprovados | Rejeições brutas com causa numérica / com aproximação |
|---|---:|---:|---:|---:|
| CBC single | 2 / 6 | 5 / 25 / 6 | 2 / 2 | 9 / 22 |
| HiGHS single | 2 / 6 | 5 / 25 / 6 | 5 / 2 | 0 / 22 |
| CBC full ou adaptive_gap, cada | 3 / 3 | 11 / 67 / 6 | 11 / 5 | 27 / 45 |
| HiGHS full ou adaptive_gap, cada | 3 / 3 | 21 / 57 / 6 | 22 / 10 | 0 / 45 |

As causas podem coexistir em um caso. Os totais contam regimes, inclusive vetores repetidos. No SLSQP, as três formulações convergiram pelo fluxo original. A checagem NRC diagnóstica posterior registrou três pequenas violações. As oito dietas aprovadas nas novas execuções HiGHS corresponderam exatamente ao mapa aprovado pelo NRC, ao mapa aplicado pela Pen e à dieta diária reportada.

Foram pareados **132 casos com hash de matriz idêntico** entre os cenários CBC e HiGHS, incluindo os seis conjuntos de single, os conjuntos de full e adaptive_gap do dia 150 e os quatro conjuntos por estratégia que continuaram idênticos no dia 151. Nesse subconjunto, as aprovações finais passaram de 19 para 29, as rejeições brutas com causa numérica passaram de 33 para zero, e as rejeições por aproximação permaneceram em 72. No dia 151 de full e adaptive_gap, a dieta anterior já diferia, apesar da identidade das quatro matrizes de referências básicas por estratégia.

No dia 152 de full e adaptive_gap, as exigências já haviam divergido e os hashes das matrizes em execução diferiram. Em comparação controlada já arquivada, HiGHS aprovou US$ 0,369587/vaca no problema original do CBC, cuja melhor aprovação custou US$ 5,691552/vaca. Na trajetória nova, HiGHS aplicou US$ 0,369657/vaca. A comparação controlada e a trajetória nova apontam na mesma direção.

Single manteve as entradas, as dietas escolhidas e o desfecho do CBC. No terceiro dia, os 12 ótimos nas três tentativas ultrapassaram o teto de PM na avaliação original por cerca de 2,03 a 164,34 g/vaca. O fluxo chegou ao limite de redução de leite e registrou apenas dois dias completos, embora o código de saída da CLI tenha sido zero.

## Referências, gaps e tempos

Full e adaptive_gap tentaram 4/5/5 referências e fizeram 60/66/66 chamadas por dia com ambos os solvers. Em HiGHS, `target_dmi` venceu nos três dias. CBC selecionou `minimum_cost`, `target_dmi` e `previous_ration`. Os limites foram US$ 0,278794 / 0,277202 / 0,275871 por vaca/dia. Os gaps HiGHS foram 23,82% / 32,11% / 25,37%, contra 25,39% / 32,11% / 95,15% no CBC. A meta de 5% ficou fora do alcance. Single usou uma referência por tentativa e fez 50 chamadas ao todo com cada solver. Seus dois gaps aprovados ficaram em 25,39% e 94,77%.

| HiGHS | Limite CBC, s | Geração CBC, s | Montagem, resolução, validação e reparo, s | LP nutricional, s, incluído na coluna anterior |
|---|---:|---:|---:|---:|
| single | 0,348 | 0,388 | 0,289 | 0,134 |
| full | 0,098 | 4,537 | 0,593 | 0,162 |
| adaptive_gap | 0,102 | 3,534 | 0,490 | 0,139 |

Nas capturas diagnósticas CBC, os blocos nutricionais equivalentes somaram 1,915 / 3,098 / 3,324 s para single, full e adaptive_gap. A instrumentação histórica não registrou o tempo do limite e do LP nutricional isoladamente. A mediana de resolução por LP nutricional no fluxo HiGHS foi de 1,51 a 1,93 ms. A fase nutricional ficou mais rápida nas três estratégias. A duração total da CLI caiu em full e subiu em single e adaptive_gap. Cada estratégia teve uma execução medida, e as capturas históricas e novas têm custos de instrumentação diferentes.

A geração de referências CBC ocupou cerca de 86% a 87% da otimização HiGHS em full e adaptive_gap. Um próximo piloto deve comparar somente essa etapa, conferindo objetivos lexicográficos e seus bloqueios, vetores por ID, deduplicação na malha, casos gerados e aprovações NRC. A troca no limite deve ser avaliada à parte, pois o cálculo usa os multiplicadores duais para certificar um limite conservador. Verificar sinais, primal, limite certificado e decisões de parada é mais importante do que igualar exatamente os multiplicadores. O tempo do limite foi cerca de 0,10 s nesses cenários completos. Uma interface mais rápida ainda resolve a relaxação que omite energia e PM.

## Artefatos

`output/nrc_cli_three_day_highs/comparison.json` contém a série diária de cada grupo, dieta por ID, consumo, custo, leite, exigências, ofertas, resíduos, casos, reparos, referências, métricas e os 132 pares de matrizes. O mesmo diretório contém `manifest.json`, insumos, `trace_highs.py`, `analyze.py` e as três execuções com `attempts.jsonl`, `phase_details.jsonl`, logs e JSONs diários ou parciais.
