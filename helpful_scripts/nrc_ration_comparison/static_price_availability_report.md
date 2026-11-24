# Sensibilidade estática a preços e disponibilidade

## Desenho

Foi usada a formulação arquivada `114502_midwest_plus_soy_market`, com seis ingredientes, consumo de referência de 22,2044 kg MS/vaca/dia e preços de referência histórica dos experimentos anteriores. Os IDs são 23 para farinha de sangue, 44 para milho em grão, 50 para silagem de milho, 104 para silagem de forragem mista, 110 para silagem de leguminosa e 167 para farelo de soja. A análise manteve as exigências NRC e os demais parâmetros de cada formulação. Os preços representam proxies históricos em US$/kg MS, com dados e fontes descritos em `details.json`.

Foram executadas 44 variantes estáticas, uma vez por método. Houve uma base, 24 alterações individuais de preço de −20%, −10%, +10% e +20%, seis retiradas, 12 cortes de teto e uma combinação de +20% no preço e −50% no teto da silagem de milho. Os limites individuais originais eram 100 kg MS/vaca/dia. Reduzi-los literalmente a 75 ou 50 ainda deixaria todos acima do teto total de 28,866 kg. Por isso, para cada ingrediente, foi calculado seu máximo efetivo na relaxação básica da formulação original. Os dois tetos experimentais foram 75% e 50% desse máximo. Para a silagem de milho, o máximo efetivo foi 17,111 kg MS/vaca/dia e o teto após o corte de 50% foi 8,555 kg. Esses tetos são restrições de inclusão por vaca, sem interpretação como estoque físico.

Os braços lineares usaram HiGHS nas três etapas e a política de produção `full` com Midwest habilitada. SLSQP executou o otimizador original com semente 42 em cada variante. Sua candidata recebeu a mesma checagem NRC e reparo de arredondamento para comparação diagnóstica. Seis resultados SLSQP precisaram de reparo. O gap SLSQP é um diagnóstico calculado com o mesmo limite inferior certificado da variante. Os custos reportados são os das melhores candidatas aprovadas encontradas por cada método.

## Resultados

| Indicador | SLSQP | HiGHS full 3 + Midwest | HiGHS full 5 + Midwest |
|---|---:|---:|---:|
| Variantes com dieta aprovada | 44/44 | 43/44 | 44/44 |
| Custo base, US$/vaca/dia | 4,405021 | 4,454577 | 4,454577 |
| MS na base, kg/vaca/dia | 22,025519 | 23,432876 | 23,432876 |
| Limite inferior base, US$/vaca/dia | 4,259672 | 4,259672 | 4,259672 |
| Gap base | 3,30% | 4,38% | 4,38% |
| Tempo mediano de otimização entre variantes, s | 0,221 | 0,160 | 0,267 |
| Vitórias da Midwest | — | 37 | 32 |

| Variante selecionada | SLSQP | HiGHS full 3 + Midwest | HiGHS full 5 + Midwest |
|---|---:|---:|---:|
| Silagem mista −20% no preço | 3,8620 | 3,9697 | 3,9697 |
| Silagem de milho +20% no preço | 4,4545 | 4,4610 | 4,4610 |
| Farelo de soja +20% no preço | 4,5607 | 4,5860 | 4,5860 |
| Retirada do milho em grão | 4,4045 | Sem candidata aprovada | 5,0934 |
| Retirada da silagem de milho | 4,4542 | 4,5034 | 4,5034 |
| Retirada da silagem de leguminosa | 4,4037 | 4,6025 | 4,6025 |
| Retirada do farelo de soja | 4,5711 | 4,5884 | 4,5884 |
| Teto efetivo da silagem de milho −50% | 4,4050 | 4,7382 | 4,7382 |
| Silagem de milho +20% no preço e teto −50% | 4,4545 | 4,7596 | 4,7596 |

Valores da segunda tabela em US$/vaca/dia. Entre as variações isoladas de preço, o custo aprovado de SLSQP variou de −12,33% a +3,54% frente à sua base. Nos dois braços HiGHS, a faixa foi de −10,89% a +2,95%. O corte de 50% no teto efetivo do ID 50 foi o único dos 12 cortes que mudou o melhor custo HiGHS. O custo subiu 6,37%. Em sete variações de preço, o orçamento cinco encontrou uma dieta mais barata que o três. A maior diferença entre os orçamentos nesse conjunto foi US$ 0,232899/vaca/dia, quando o preço da silagem de leguminosa caiu 20%.

A dieta HiGHS da base usou 10,933 kg de silagem de milho, 10,093 de silagem de leguminosa e 2,407 de farelo de soja. Com o preço da silagem de milho 20% maior, a dieta aprovada substituiu toda a silagem de milho e passou a 6,187 kg de milho em grão, 12,144 de silagem de leguminosa e 2,245 de farelo de soja. Na retirada de farelo de soja, os dois braços lineares aumentaram a silagem de milho para 12,507 kg e introduziram milho em grão e silagem mista.

### Falha de busca versus inviabilidade

A relaxação básica permaneceu viável nas 44 variantes. Ao retirar o milho em grão, o orçamento três encontrou seis ótimos lineares, todos rejeitados por insuficiência de energia total no NRC, e 12 regimes lineares inviáveis. SLSQP aprovou uma dieta de US$ 4,4045 e o orçamento cinco aprovou US$ 5,0934 com a referência de máximo concentrado. Portanto, a única ausência de candidata aprovada foi uma limitação da busca com três referências. Nenhuma variante teve inviabilidade nutricional comprovada.

No cenário combinado, a referência Midwest projetada excedeu o novo teto da silagem de milho e foi descartada. A candidata aprovada no cenário apenas com +20% no preço, de US$ 4,4610 e sem silagem de milho, também passou na validação NRC sob o teto do cenário combinado. A busca desse cenário encontrou US$ 4,7596. A diferença mostra o efeito da escolha de referências no conjunto de candidatas, mesmo quando uma dieta mais barata continua admissível.

### Preços-sombra e custos reduzidos

Os duais foram extraídos do LP do regime vencedor antes do arredondamento e conferidos contra o vetor bruto. Na base, cálcio, fósforo e energia total estavam ativos. O preço-sombra da energia total foi US$ 0,027195 por Mcal de aumento no RHS linear. No corte de 50%, o teto da silagem de milho estava ativo e o custo reduzido dessa variável foi −US$ 0,002496 por kg MS no teto. Os valores são locais, condicionais à matriz aproximada, à referência e ao regime vencedor. Eles não medem o efeito global no NRC nem incluem trocas futuras de referência.

### Conclusão preliminar

Os métodos se adaptaram à maioria dos choques por substituição de ingredientes. O orçamento cinco recuperou a única falha de cobertura do orçamento três, com maior tempo medido. O cenário combinado mostrou que a geração de candidatas continua a limitar a qualidade econômica mesmo quando a certificação NRC está correta. A comparação cobre uma vaca, um cardápio e uma execução por variante. Os tempos resumem essa carga de casos e não estimam variabilidade entre repetições.

## Arquivos

- `summary.csv` contém custo, desvio percentual da base por método, consumo, gap, tempo e aprovação.
- `composition.csv` contém quantidades e substituições por ID, com quantidades vazias quando não há dieta aprovada.
- `lp_constraints.csv` e `lp_ingredients.csv` contêm preços-sombra, custos reduzidos, folgas e atividade no LP vencedor.
- `details.json` contém os insumos, tetos, dietas, diagnósticos e resíduos de validação.

As saídas estão em `output/nrc_price_availability_sensitivity/`. O [roteiro experimental](static_price_availability.py) usa os módulos existentes do RuFaS, sem alterar a produção.
