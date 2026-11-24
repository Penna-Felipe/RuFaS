# Piloto isolado de HiGHS na geração de referências NRC

Executado em 24 de novembro de 2026, no HEAD `f025c79be` com o piloto nutricional local, Python 3.12.10, PuLP 3.3.2, CBC 2.10.3 e highspy 1.16.0. Foram usados 12 cenários estáticos e 15 tentativas reconstruídas da CLI de três dias, com exigências, peso, cardápio, preços e dieta anterior arquivados. As 15 tentativas incluem entradas repetidas ou parecidas e retentativas condicionais à trajetória original. Cada braço executou o adaptador no modo `full` com cinco vagas para poder explorar os quatro objetivos em todas as formulações. A dieta anterior compatível ocupou uma vaga quando disponível. Ambos os braços usaram HiGHS com uma thread nos casos nutricionais e CBC no limite. A única diferença de configuração entre braços foi o solver passado a `build_basic_reference()`.

Foram feitas cinco repetições cronometradas por braço e formulação, com ordem alternada, mais uma captura detalhada fora da medição. O cronômetro completo cobre a chamada ao adaptador, incluindo geração de referências, limite, montagem, solução, certificação NRC e reparo. O experimento usou entradas congeladas e não executou uma simulação dinâmica.

## Desempenho e resultado nutricional

Os tempos são medianas entre as 27 medianas por formulação, calculadas a partir de cinco repetições.

| Etapa, ms | A · Referências CBC | B · Referências HiGHS |
|---|---:|---:|
| Menor custo | 186,00 | 10,81 |
| Máxima forragem | 209,32 | 11,62 |
| Máximo concentrado | 209,47 | 12,30 |
| Meta de matéria seca | 210,42 | 12,57 |
| Geração em cada formulação | 818,39 | 49,01 |
| Limite CBC | 25,74 | 27,04 |
| Montagem, resolução e validação nutricional | 107,87 | 108,20 |
| Otimização completa | 966,14 | 178,98 |

A mediana da geração caiu **16,7 vezes**, e a mediana completa, **5,4 vezes**. A mediana por objetivo inclui as tentativas que terminaram com erro de geração ou vetores incompatíveis. As medianas por etapa e por formulação são calculadas separadamente.

| Contagem em um passe pelas 27 formulações | A · CBC | B · HiGHS |
|---|---:|---:|
| Chamadas para gerar referências | 873 | 872 |
| Chamadas totais, incluindo o limite | 1.590 | 1.595 |
| Referências geradas / compatíveis / duplicadas | 108 / 106 / 2 | 107 / 107 / 2 |
| Referências enviadas aos LPs nutricionais, incluindo anteriores | 115 | 116 |
| Casos nutricionais ótimos / inviáveis | 592 / 98 | 598 / 98 |
| Aprovações brutas / finais | 318 / 261 | 321 / 268 |
| Aprovações finais após reparo | 128 | 138 |
| Formulações aprovadas / sem dieta | 27 / 0 | 27 / 0 |
| Gaps de até 5% | 3 | 4 |

As 15 tentativas da CLI tiveram o mesmo melhor custo entre os braços a US$ 1e-9 e gaps entre **23,82% e 32,11%**. Nos cenários estáticos, dez dos doze tiveram diferença abaixo de US$ 0,000001/vaca/dia. No cenário da vaca 123802 com soja e preços de mercado, a referência de meta de MS passou no HiGHS e o custo caiu de **US$ 3,983624 para US$ 3,771044/vaca/dia**, com gap de **8,17% para 3,00%**. No cardápio de cinco ingredientes e preços de mercado da mesma vaca, o custo subiu de **US$ 3,901144 para US$ 3,904341/vaca/dia** com a perda da referência de meta de MS. O limite CBC foi idêntico nos dois braços em todas as 27 formulações. A contagem de metas atingidas usa o gap da melhor dieta em `full`.

## Compatibilidade, restrições e objetivos

A captura confirmou as mesmas expressões dos objetivos, a mesma ordem de hierarquia, as mesmas restrições básicas e a mesma folga de bloqueio de **1e-6**. Os lados direitos dos bloqueios são construídos com o ótimo entregue em cada etapa, de modo que diferenças nos valores encontrados podem se acumular. As maiores diferenças nos ótimos primários foram **9,45e-8 US$/vaca/dia** em menor custo, **9,30e-7 kg** em máxima forragem, **4,71e-7 kg** em máximo concentrado e **1,43e-8 kg** no desvio da meta de MS. Entre os estágios secundários comparáveis, as maiores diferenças foram **1,81e-5 US$/vaca/dia** no desempate por custo e **1,07e-4 kg** nos desempates por ingrediente. O teste comparou os objetivos e os resíduos, admitindo vetores diferentes.

Dos 107 pares em que ambos produziram vetor, 70 ficaram em chaves distintas na malha de seis casas. A maior distância L1 entre referências do mesmo objetivo foi **0,000301 kg MS/vaca**. A distância L1 mediana entre objetivos dentro da mesma formulação permaneceu em **30,83 kg** nos dois braços. Cada braço descartou duas duplicatas nas mesmas formulações.

CBC produziu duas referências com pequenas quantidades negativas do ID 23, que o filtro de compatibilidade rejeitou. Entre as referências CBC avaliáveis, três de máximo concentrado ultrapassaram a tolerância do teto de MS. O maior excesso foi **7,81e-7 kg**. As 107 referências produzidas por HiGHS passaram pelo filtro de limites individuais e pelas oito restrições básicas nas unidades e tolerâncias originais. A compatibilidade da referência permite calcular coeficientes. A certificação das dietas candidatas continua usando o NRC completo.

No caso estático `123802_midwest_five_market`, HiGHS considerou inviável o sexto estágio da sequência de meta de MS, o desempate do ingrediente 104. O estágio anterior havia aceitado um déficit de fósforo de **4,64e-8 g**. Na matriz reconstruída com os mesmos bloqueios, HiGHS repetiu a inviabilidade com ou sem presolve. CBC reportou ótimo nessa matriz, com o último ingrediente cerca de **5,36e-7 kg abaixo do limite zero**. O resultado indica sensibilidade numérica na sequência de bloqueios. Na comparação principal, a busca prosseguiu pelas outras referências, gerando a dieta aprovada de US$ 3,904341. A matriz e os vetores desse diagnóstico estão arquivados.

## Ensaio preliminar do limite inferior

PuLP 3.3.2 atribui `solution.row_dual` da API HiGHS a `LpConstraint.pi`. No problema de minimização, o sinal admissível é positivo para uma linha `Ax >= b` e negativo para `Ax <= b`, admitindo zero nos dois casos. O teste sintético confirmou **+1** e **−1** em desigualdades ativas. Nas 27 relaxações reais, os **216 multiplicadores** estavam presentes e finitos com HiGHS, com 49 positivos, 167 nulos e nenhuma inversão. CBC teve o mesmo padrão de sinais.

Para multiplicadores com os sinais válidos, o limite usa `y·b + min_box((c − Aᵀy)·x)`. A minimização na caixa trata o restante da estacionariedade pelos limites dos ingredientes. O cálculo existente corrige sinais, usa aritmética racional e arredonda o resultado para baixo. O modo tolerante amplia a caixa e modifica as linhas conforme as tolerâncias do validador. Portanto, a validade do certificado decorre da desigualdade e dos limites finitos, inclusive quando os duais são aproximados.

Em cada uma das 27 entradas, o diagnóstico executou CBC e HiGHS na relaxação primária e resolveu com HiGHS também a relaxação tolerante escrita explicitamente. A maior diferença entre os ótimos primais básicos foi **9,45e-8 US$/vaca/dia**. Os certificados tolerantes HiGHS coincidiram com o ótimo explícito a **7,11e-15 US$/vaca/dia**, no máximo, e ficaram entre **6,24e-10 e 4,52e-7 US$/vaca/dia** acima dos certificados CBC. Esses são resultados do diagnóstico isolado. O limite efetivamente usado para calcular o gap de ambos os braços foi CBC.

O ganho de tempo justifica priorizar a geração de referências no próximo piloto autorizado. Antes de promovê-la ao fluxo de produção, convém manter o caso de inviabilidade do sexto desempate como regressão e avaliar o impacto do gerador em estratégias com orçamento curto. O ensaio dual indica compatibilidade com `dual_bound()`. A mudança no limite tem prioridade menor e merece sua própria regressão de decisões próximas ao limiar do gap.

## Artefatos e reprodução

O [script experimental](reference_solver_pilot.py) usa os módulos de produção pela injeção de solvers existente. O diretório `output/nrc_reference_solver_pilot/` contém `results.json`, com tempos por objetivo e repetição, hierarquia, vetores, chaves de deduplicação, resíduos básicos e NRC, candidatas, custos, gaps, multiplicadores e certificados. `diagnostic_stage.json` contém a reconstrução adicional do desempate e o teste de sinais.

```powershell
py -3.12 -m helpful_scripts.nrc_ration_comparison.reference_solver_pilot --runs 5 --output output/nrc_reference_solver_pilot_repro
```
