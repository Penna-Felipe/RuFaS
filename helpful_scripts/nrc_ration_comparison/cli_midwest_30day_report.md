# Simulação exploratória de 30 dias com a referência Midwest

## Desenho experimental

Foram executados os dias julianos 150 a 179 de 2013 no cenário freestall `animals_only`, com reformulação diária, NRC e semente 42. A configuração geral arquivada mudou apenas na data de término. Os três braços usaram a mesma população inicial, os mesmos arquivos ambientais e biológicos e o mesmo arquivo de ingredientes e preços. O manifesto registra a revisão e os hashes dos insumos. Os dois braços lineares usaram HiGHS nas três etapas, estratégia `full` e a receita Midwest habilitada. Houve uma repetição por configuração. Os três processos rodaram em paralelo para atender ao prazo da apresentação. Os tempos totais incluem a inicialização da CLI e a escrita das saídas sob recursos compartilhados.

Cada execução registrou o marcador de conclusão e produziu 30 dias com leite e alimentação reportados para as quatro baias. Os custos representam a matéria seca aplicada valorizada aos preços de entrada do cenário. A coluna de custo por kg de leite usa o custo de todas as baias sobre a produção de leite. Os CSVs também trazem esse indicador usando apenas o custo da lactação.

## Comparação consolidada

| Métrica | SLSQP original | HiGHS full, 3 + Midwest | HiGHS full, 5 + Midwest |
|---|---:|---:|---:|
| Dias concluídos | 30 | 30 | 30 |
| Custo aplicado, todas as baias, US$ | 1.226,76 | 1.256,07 | 1.248,65 |
| Custo aplicado na lactação, US$ | 869,97 | 890,97 | 883,55 |
| Leite acumulado, kg | 98.923,12 | 99.814,17 | 99.814,17 |
| Matéria seca aplicada, todas as baias, kg | 104.501,78 | 105.120,64 | 105.120,64 |
| Matéria seca aplicada na lactação, kg | 79.457,37 | 80.012,88 | 80.012,88 |
| Custo alimentar total por kg de leite, US$ | 0,012401 | 0,012584 | 0,012510 |
| Otimização, todas as baias, s | 8,17 | 10,22 | 15,24 |
| Otimização, lactação, s | 3,26 | 5,33 | 10,38 |
| Tempo total da CLI, s | 65,66 | 68,24 | 73,21 |
| Reformulações bem-sucedidas / rejeitadas, todas as baias | 90 / 0 | 90 / 0 | 90 / 0 |
| Reformulações bem-sucedidas / rejeitadas, lactação | 30 / 0 | 30 / 0 | 30 / 0 |
| Chamadas na lactação | 30 | 819 | 1.980 |
| Chamadas em todas as baias | 90 | 879 | 2.040 |
| Midwest explorada / vencedora | — | 30 / 0 | 1 / 0 |
| Gap mínimo / mediano / máximo | — | 23,77% / 24,18% / 33,48% | 23,78% / 24,19% / 32,11% |
| Quartis Q1 / Q3 do gap | — | 24,04% / 26,85% | 24,04% / 25,35% |
| Dias com gap de até 5% | — | 0 | 0 |

No orçamento 3, a dieta anterior venceu em 17 dias e menor custo em 13. No orçamento 5, a dieta anterior venceu em 16 dias e a meta de MS em 14. A referência Midwest não foi vencedora em nenhuma das duas configurações. O orçamento 5 custou US$ 7,42 a menos que o orçamento 3, com a mesma produção de leite e a mesma matéria seca aplicada na lactação. Para isso, fez 2,42 vezes as chamadas de lactação e usou 1,95 vez o tempo medido de otimização da lactação.

Na lactação, os dois braços HiGHS aplicaram exatamente as quantidades por ingrediente aprovadas pelo NRC. Entre os LPs nutricionais, o orçamento 3 teve 217 casos aprovados, 263 rejeitados pelo NRC e 60 inviáveis. O orçamento 5 teve 284, 554 e 62, respectivamente. Esses resultados são contagens de regimes explorados. Nenhuma rejeição de candidata interrompeu uma reformulação, e os três braços ficaram sem falhas de reformulação. SLSQP convergiu nas 30 tentativas de lactação pelo fluxo original. Na checagem posterior com o critério estrito aplicado às candidatas lineares, 5 de 30 dietas SLSQP passaram no vetor aplicado. As 25 restantes tiveram 15 registros de violação do teto de MS e 12 de déficit de PM, com sobreposição em duas dietas. Essa verificação posterior é distinta do critério de aceitação do SLSQP na simulação.

## Leitura para a apresentação

- Os dois orçamentos mantiveram reformulação diária durante 30 dias. O orçamento 3 reduziu o esforço de otimização frente ao 5. O 5 obteve custo alimentar ligeiramente menor.
- Descritivamente, os braços HiGHS produziram 891,06 kg a mais que SLSQP e tiveram custo alimentar total por kg de leite mais alto. As exigências completas da lactação coincidiram com SLSQP apenas no dia inicial. Entre os braços HiGHS, as dietas divergiram no primeiro dia e as exigências no terceiro. Os acumulados são efeitos de trajetórias, com uma semente e preços ilustrativos.
- A Midwest nunca venceu neste cenário. Os braços lineares tinham a opção habilitada. Uma comparação com a opção desabilitada é necessária para estimar o efeito causal de explorar a Midwest em orçamento fixo.
- Os gaps ficaram distantes de 5% e são calculados contra a relaxação básica. Um gap alto combina o custo da dieta aprovada com a folga desse limite inferior. As medições de tempo desta rodada são exploratórias e incluem concorrência entre processos.

Trabalhos futuros incluem generalizar o suporte a referências externas, investigar geração dinâmica de referências e medir a sensibilidade das dietas e dos custos a variações de preços. Replicações com outras sementes e um braço de controle com a Midwest desabilitada permitiriam estimar a generalização e o efeito isolado da opção.

## Arquivos para gráficos

- `output/nrc_midwest_30day/daily_metrics.csv` contém 90 linhas, uma por cenário e dia, com custo e leite acumulados, matéria seca, tempo diário e acumulado de otimização, gap e taxa de sucesso diária e acumulada.
- `output/nrc_midwest_30day/summary.csv` contém os acumulados, os tempos totais e a distribuição de gaps para tabelas e gráficos de barras.
- `output/nrc_midwest_30day/attempts.csv` contém resultados por tentativa, chamadas, referência vencedora, diagnóstico regional e causas de rejeição por restrição.
- `output/nrc_midwest_30day/daily_by_group.csv` contém custo, matéria seca e composição por baia.
- `output/nrc_midwest_30day/summary.json` contém a consolidação detalhada. Os subdiretórios `runs/` preservam saídas da CLI, logs, dietas e fases cronometradas. Os roteiros e o manifesto estão no mesmo diretório.
