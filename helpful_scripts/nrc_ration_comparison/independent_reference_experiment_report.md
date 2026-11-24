# Referências regionais independentes com coeficientes fixos

## Entradas e projeção

O ensaio usou os 12 cenários estáticos e as 15 tentativas reconstruídas da CLI. HiGHS 1.16.0 via PuLP 3.3.2, com uma thread, resolveu geração, limite e LPs nutricionais. Em cada formulação, os braços receberam os mesmos ingredientes, preços, exigências, limites e dieta anterior quando disponível. As tentativas reconstruídas são entradas congeladas e algumas representam a mesma situação ou retentativas da trajetória anterior.

Os quatro arquivos regionais têm receitas explícitas para CALF, GROWING, CLOSE_UP e LAC_COW. O arquivo `no_feed.json` não contém receitas. A auditoria em `inventory.json` registra os ingredientes, percentuais e a presença no NRC por arquivo e grupo. Os IDs ausentes do NRC na lactação foram 301 e 302 para Midwest, 301 e 303 para Northeast, e 301 e 305 para Southwest e Intermountain. A receita completa de nenhuma região é elegível nos cardápios auditados.

| Receita LAC_COW | IDs originais | IDs aproveitados | Participação original retida |
|---|---|---|---:|
| Midwest | 23, 44, 50, 104, 110, 301, 302 | 23, 44, 50, 104, 110 | 71,52% |
| Northeast | 44, 51, 100, 110, 301, 303 | 44, 110 | 27,48% |
| Southwest | 44, 51, 100, 108, 301, 305 | 44 | 19,71% |
| Intermountain | 44, 51, 100, 108, 301, 305 | 44 | 16,99% |

Para cada receita, foram removidas as participações positivas de IDs ausentes do cardápio ou do NRC. O peso restante de cada ingrediente foi dividido pela soma retida e multiplicado pela meta inicial de MS. Nenhum ingrediente foi adicionado. As projeções passaram pelo filtro de compatibilidade e limites individuais existente. A Midwest resultou em percentuais 1,035 / 21,407 / 52,363 / 0,517 / 24,678, na ordem dos IDs da tabela. Northeast virou 50/50 e Southwest e Intermountain viraram 100% do ID 44. Essas últimas são projeções fortemente descaracterizadas e servem ao diagnóstico da sensibilidade dos coeficientes. A regra de compatibilidade de uma referência permite que ela seja usada para calcular coeficientes. A dieta candidata passa pelas restrições NRC completas.

## Políticas e orçamento

A percorre as fontes atuais na ordem de produção, com a dieta anterior seguida dos quatro objetivos básicos. B adiciona Midwest. C adiciona todas as projeções, em ordem decrescente de participação retida. “Depois” coloca as externas após as atuais. “Cedo” as insere após menor custo, preservando a tentativa anterior quando disponível. “Primeiro” avalia as externas antes das atuais. O orçamento conta referências distintas, deduplicadas à precisão de seis casas. As comparações exploram até o orçamento ou até esgotar as fontes, com a meta de 5% reportada retrospectivamente. Houve três repetições cronometradas por combinação, em ordem alternada. Os tempos de geração medem as chamadas de construção na busca e a seleção de vetores externos já projetados. A projeção do catálogo inteiro, cronometrada à parte, levou mediana de 0,052 ms. O diagnóstico nutricional extra foi executado fora do cronômetro.

Todas as políticas e todos os orçamentos aprovaram **27/27**. O limite certificado foi idêntico entre braços de cada formulação. Os custos abaixo são comparados com A no mesmo orçamento. Os tempos são medianas das medianas das três repetições por formulação.

| Orçamento | Política | Custo melhor / pior | Gap ≤ 5% | Referências | LPs totais | Geração, ms | Otimização, ms |
|---|---|---:|---:|---:|---:|---:|---:|
| 2 | A | 0 / 0 | 3 | 54 | 675 | 15,95 | 69,34 |
| 2 | B cedo | 3 / 0 | 6 | 54 | 549 | 10,10 | 58,66 |
| 2 | C cedo | 3 / 0 | 6 | 54 | 549 | 9,68 | 59,38 |
| 2 | C primeiro | 3 / 24 | 6 | 54 | 351 | 0,00 | 41,65 |
| 3 | A | 0 / 0 | 3 | 81 | 1.062 | 25,42 | 103,70 |
| 3 | B cedo | 3 / 0 | 6 | 81 | 837 | 15,60 | 91,22 |
| 3 | C cedo | 3 / 0 | 6 | 81 | 711 | 10,04 | 78,87 |
| 3 | C primeiro | 3 / 24 | 6 | 81 | 513 | 0,00 | 64,61 |
| 5 | A | 0 / 0 | 4 | 116 | 1.595 | 47,16 | 155,34 |
| 5 | B depois | 2 / 0 | 6 | 132 | 1.691 | 48,53 | 173,06 |
| 5 | B cedo | 2 / 11 | 6 | 132 | 1.592 | 37,31 | 151,20 |
| 5 | C depois | 2 / 0 | 6 | 135 | 1.709 | 47,17 | 164,96 |
| 5 | C cedo | 2 / 18 | 6 | 135 | 1.161 | 16,64 | 128,66 |
| Todas | A | 0 / 0 | 4 | 116 | 1.595 | 45,89 | 159,65 |
| Todas | B depois | 2 / 0 | 6 | 143 | 1.757 | 46,39 | 177,39 |
| Todas | C depois | 2 / 0 | 6 | 197 | 2.081 | 45,80 | 217,54 |

B/C depois com orçamentos 2 e 3 reproduziram A porque o orçamento terminou nas fontes atuais. C primeiro e C cedo com orçamento 5 tiveram a mesma seleção econômica. Com exploração completa, a ordem manteve as mesmas aprovações e custos por braço. Os LPs totais incluem o limite, a geração lexicográfica e os seis regimes por referência efetivamente explorada. A deduplicação descartou Intermountain como idêntica a Southwest em todas as formulações e dois vetores de meta de MS duplicados com menor custo na busca completa. A distância L1 mediana entre referências de uma mesma formulação foi 30,39 kg MS em A, 35,59 em B e 35,18 em C na ordem depois.

Na busca completa, Midwest reduziu o melhor custo de 4,723562 para 4,454577 e de 5,929713 para 5,550377 US$/vaca/dia em dois cenários estáticos com soja e preços de mercado. A maior redução foi 0,379336. Com orçamento de duas referências e inserção cedo, Midwest melhorou três cenários, com redução máxima de 0,647575. Apenas as projeções externas em primeiro lugar pioraram 24 melhores custos com orçamentos 2 e 3. Antecipar várias externas com orçamento cinco deslocou referências básicas valiosas. O maior aumento nesse caso foi 0,042050 US$/vaca/dia.

## Erros nutricionais e candidatas recuperadas

| Busca completa | Aprovadas | Rejeitadas NRC | Inviáveis LP | Rejeições brutas com aproximação | Rejeições brutas numéricas |
|---|---:|---:|---:|---:|---:|
| A | 268 | 330 | 98 | 277 | 0 |
| B | 337 | 361 | 160 | 308 | 0 |
| C | 387 | 481 | 314 | 417 | 0 |

As contagens são por regime e podem incluir vetores repetidos. As rejeições brutas por aproximação são subconjunto das rejeições NRC. O arquivo detalhado registra a classificação, os resíduos das matrizes, a validação bruta, arredondada e reparada, e os erros de oferta por candidata. A classificação compara resíduos NRC e linearizados aos limiares existentes. O maior número absoluto de rejeições em C acompanha o maior número de LPs.

| Referência | Ótimos / aprovados | Erro absoluto mediano de energia manutenção / crescimento / lactação, Mcal | Erro absoluto mediano de PM, g |
|---|---:|---:|---:|
| Menor custo | 151 / 98 | 4,09 / 3,64 / 3,27 | 76,95 |
| Meta de MS | 141 / 84 | 4,04 / 3,59 / 3,22 | 83,87 |
| Midwest | 100 / 69 | 4,51 / 4,09 / 3,46 | 64,83 |
| Northeast | 88 / 35 | 4,88 / 4,32 / 3,89 | 128,91 |
| Southwest | 82 / 15 | 6,74 / 6,08 / 5,24 | 296,31 |

Na Midwest, 58 ótimos mantiveram TDN como limitante, 30 saíram de empate linear TDN/RDP para RDP no NRC e 12 saíram de empate para TDN. Northeast teve 58 TDN→TDN e 30 empate→RDP. Southwest teve 52 e 30, respectivamente. Nas fontes atuais houve também troca estrita RDP→TDN em 40 casos, incluindo dieta anterior, máxima forragem e meta de MS. Comparações de erro entre fontes abrangem os ótimos que cada fonte gerou e não constituem pares com a mesma dieta candidata.

Midwest ofereceu novas candidatas certificadas e venceu nos dois cenários econômicos, em regimes em que A já tinha alguma candidata aprovada. Northeast acrescentou 35 candidatas aprovadas e não venceu. Southwest abriu cinco aprovações de manutenção/RDP sem precedente em A, em cinco tentativas arquivadas, mas custaram entre US$ 9,86 e US$ 10,24/vaca/dia. Quatro registros correspondem ao dia 151 em trajetórias distintas. Em `single/152/1`, a dieta anterior isolada falhou. Midwest aprovou 0,406778 e Northeast 0,599962 US$/vaca/dia. A busca A com duas referências já aprovava 0,377258 nesse problema, e A completa aprovava 0,369587. Assim, a recuperação frente à dieta anterior isolada não representa vantagem frente à busca atual com mais referências.

## Política recomendada

Testar **uma única referência Midwest adaptada**, com registro da fração retida e dos ingredientes removidos. Para orçamento 2 ou 3, a melhor ordem observada foi anterior quando disponível, menor custo e então Midwest, usando apenas as vagas que restarem. Para orçamento 5, priorizar as referências atuais e usar Midwest quando sobrar uma vaga. Essa ordem acrescentou aprovações e melhorou custos sem perda observada sob o mesmo teto. O benefício depende da distribuição de cardápios e preços. As projeções Northeast e Southwest ficaram muito distantes das receitas originais e não melhoraram o melhor custo da busca completa. A inclusão de várias projeções fortemente alteradas fez mais LPs, e antecipá-las deslocou fontes básicas úteis.

O [roteiro isolado](independent_reference_experiment.py) pode ser reproduzido com `py -3.12 -m helpful_scripts.nrc_ration_comparison.independent_reference_experiment --runs 3 --output output/nrc_independent_references_repro`. Os resultados estão em `output/nrc_independent_references/`. A promoção ao fluxo de produção depende de autorização.
