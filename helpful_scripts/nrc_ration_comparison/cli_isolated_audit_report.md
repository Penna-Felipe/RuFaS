# Auditoria isolada das reformulações NRC da baia de lactação

## Reconstrução e comparação controlada

A reprodução lê as 15 linhas de `attempts.jsonl` das quatro execuções diagnósticas anteriores. São três formulações em cada trajetória SLSQP, full e adaptive_gap e seis tentativas em single. Nenhum animal ou dia da simulação foi executado novamente. O código carregou `NRC_comp.csv` pelo mesmo construtor de ingredientes do motor e usou as listas de IDs na ordem dos registros. O peso da baia vem das médias reportadas no cenário full. Para as tentativas single do terceiro dia, que ficaram sem relatório diário de peso, o mesmo valor reproduz exatamente os resíduos registrados. As 189 avaliações arquivadas reproduziram os 14 resíduos com diferença máxima observada igual a zero. Todas as decisões PuLP registradas foram reproduzidas.

A produção de leite usada na formulação foi reconstruída de `NEL_lactação`, dividindo pela densidade de energia do leite calculada com gordura 4%, proteína verdadeira 3,2% e lactose 4,85%, constantes que o RuFaS passa ao NRC em cada animal. A proporcionalidade permite recuperar a média da baia, até o erro de ponto flutuante. O relatório de leite produzido após a formulação é outra medição. As exigências da primeira tentativa definem o teto de MS e o teto de PM para as tentativas seguintes. O piso de cada nutriente usa as exigências vigentes na tentativa. Os valores exatos de todas as exigências, inclusive as cinco componentes de energia, Ca, P, P de processo e aminoácidos, permanecem no JSON.

| Trajetória de origem | Dia/tentativa | Peso, kg | Leite usado, kg/vaca | MS prevista corrente / faixa, kg/vaca | Faixa de PM, g/vaca |
|---|---|---:|---:|---|---|
| Todas | 150/1 | 632,303929 | 41,853258 | 25,874661 / 18,112263–33,637059 | 2843,456938–4265,185407 |
| Todas | 151/1 | 634,297601 | 41,593362 | 25,735195 / 18,014637–33,455754 | 3119,804028–4679,706042 |
| single | 151/2 | 634,297601 | 41,343362 | 25,648748 / 17,954124–33,455754 | 3104,661312–4679,706042 |
| full, adaptive_gap e single | 152/1 | 633,403698 | 41,393783 | 25,600440 / 17,920308–33,280572 | 2860,905849–4291,358773 |
| single | 152/2 | 633,403698 | 41,143783 | 25,514307 / 17,860015–33,280572 | 2846,597100–4291,358773 |
| single | 152/3 | 633,403698 | 40,893783 | 25,428174 / 17,799722–33,280572 | 2832,288352–4291,358773 |
| SLSQP | 152/1 | 633,403698 | 41,393783 | 25,600440 / 17,920308–33,280572 | 2867,618938–4301,428407 |

No problema full do dia 152, a exigência é 10,056383 Mcal de manutenção, 0,017103 de atividade, 0,482405 de crescimento, 0,308778 de gestação e 31,102877 de lactação, totalizando 41,967546 Mcal/vaca/dia. Cálcio é 72,177165 g e fósforo 65,072143 g, acima do fósforo de processo de 39,542881 g. O fósforo de processo na trajetória single foi 39,423909 g na primeira tentativa desse dia. A diferença é inativa na restrição, que usa o maior dos dois valores. Os IDs 23, 44, 50, 104, 110, 167 e 231 custam, respectivamente, US$ 0,10, 0,50, 0,01, 0,01, 0,01, 0,37 e 0,60 por kg de MS. Os limites efetivamente passados para ambos os solvers são 0 e 100 kg MS/vaca/dia por ingrediente, antes do teto conjunto de MS.

A tabela a seguir usa as exigências de cada linha para os dois solvers. SLSQP iniciou da dieta anterior daquela baia se registrada, ou usou semente 42. A mesma validação NRC e o mesmo reparo de seis casas foram aplicados aos dois. Custos brutos de SLSQP abaixo passaram o NRC, mas alguns ficaram sem solução aprovada após arredondamento e reparo. No dia 152 também foram feitos três arranques diagnósticos independentes com sementes 42, 43 e 44. PuLP na trajetória SLSQP é uma reprodução contrafactual com a estratégia full e a dieta anterior registrada naquela trajetória.

| Origem | Dia/tentativa | SLSQP bruto, US$/vaca | SLSQP aprovado, mesmo arranque | PuLP aprovado, US$/vaca |
|---|---|---:|---:|---:|
| Todas | 150/1 | 0,367526 | 0,367526 | 0,373645 |
| full / adaptive_gap | 151/1 | 0,401770 | — | 0,408320 |
| single | 151/1 | 0,401770 | — | — |
| single | 151/2 | 0,399467 | — | 5,274511 |
| SLSQP | 151/1 | 0,405576 | — | 0,408320 |
| full / adaptive_gap | 152/1 | 0,362986 | — | 5,691552 |
| single | 152/1 | 0,367358 | 0,367358 | — |
| single | 152/2 | 0,365218 | — | — |
| single | 152/3 | 0,363077 | 0,363077 | — |
| SLSQP | 152/1 | 0,363991 | 0,363991 | 0,378293 |

No problema full do dia 152, o SLSQP obteve dieta aprovada a **US$ 0,369054** com arranque frio de semente 43 e a US$ 0,371052 com semente 42 e reparo. O arranque da dieta anterior obteve US$ 0,362986 no vetor bruto. O arredondamento provocou déficit de PM e a rotina vigente não encontrou reparo. A dieta aprovada de US$ 0,369054 usa os IDs 23, 50, 104 e 110. Na de US$ 5,691552, o ID 44 responde por US$ 3,002141 e o 167 por US$ 2,369777, juntos 94,39% do custo. Os IDs 50 e 231 respondem pelos US$ 0,319634 restantes. O consumo total de ambas as dietas é praticamente o mesmo.

## Referências fixadas e candidatas do dia 152

A referência Midwest foi construída com as proporções originais dos IDs compatíveis, renormalizadas para a MS-alvo inicial. Os IDs sem participação original entraram com zero. A última referência usa a solução SLSQP bruta somente para diagnóstico da aproximação. A coluna HiGHS é o melhor custo **bruto** entre as dietas aprovadas pela mesma validação. A matriz PuLP foi passada a um solver independente para isolar a precisão do vetor CBC. As quantidades finais e os custos após reparo estão no JSON.

| Referência | Desconto TDN | Mínimo aprovado pelo CBC, US$ | Mínimo aprovado na mesma matriz com HiGHS, US$ |
|---|---:|---:|---:|
| Anterior da Pen full | 1,000000 | 5,691552 | 5,691552 |
| LP básico de menor custo | 1,000000 | — | 0,377258 |
| Máxima forragem | 1,000000 | 5,691796 | 5,691796 |
| Máximo concentrado | 0,784802 | — | — |
| Meta de MS | 1,000000 | — | 0,369587 |
| Midwest | 0,910018 | 0,406778 | 0,406778 |
| SLSQP diagnóstico | 1,000000 | 6,613502 | 6,613502 |

Com a dieta anterior da trajetória single, o desconto congelado foi 0,832368, contra 1,0 na anterior de full. Ambas as referências anteriores tinham 33,455753 kg MS, cerca de 0,175181 kg acima do teto do terceiro dia. O código permite referências com ingestão positiva e ingredientes dentro dos limites, mesmo que falhem o NRC corrente. A referência de máximo concentrado do dia 152 ficou aproximadamente 0,000000288 kg abaixo do teto. Ela foi problemática pela transposição dos fatores nutricionais, embora o pequeno excesso de MS verificado em outros experimentos justifique continuar auditando a saída do gerador. As cinco referências independentes da anterior e do SLSQP deram os mesmos resultados nos problemas full e single desse dia. A candidata cara persistiu com máxima forragem sem a dieta anterior. Já Midwest encontrou uma dieta de US$ 0,406778 com o CBC vigente e fora das cinco referências de produção, sem usar o SLSQP como entrada.

### Candidatas CPU/CBC com quantidades em kg de MS/vaca/dia

Os IDs omitidos têm zero. A linha cara representa a dieta final após reparo. As demais são os vetores brutos. Os regimes manutenção/TDN e lactação/TDN repetiram as mesmas quatro candidatas baratas. A energia de manutenção, crescimento e lactação abaixo está em Mcal/vaca/dia e a proteína em g/vaca/dia.

| Referência | Custo, US$ | Composição | MS | Energia linear → NRC, na ordem man./cres./lact. | PM linear → NRC |
|---|---:|---|---:|---|---|
| Anterior full | 0,362854 | 23=0,33387061, 50=6,81910460, 110=26,127597 | 33,28057221 | 47,00810 / 27,58110 / 47,09675 → iguais | 2860,90586 → 2860,02112 |
| Máxima forragem | 0,362980 | 23=0,33527261, 50=6,82466110, 110=26,120638 | 33,28057171 | 47,01054 / 27,58326 / 47,09872 → iguais | 2860,90582 → 2860,86448 |
| Meta de MS | 0,369587 | 23=0,40867951, 50=7,11559490, 110=25,756298 | 33,28057241 | 47,13838 / 27,69616 / 47,20202 → iguais | 2860,90587 → 2905,02172 |
| Menor custo básico | 0,377258 | 23=0,49391162, 50=7,45339560, 110=25,333265 | 33,28057222 | 47,28682 / 27,82725 / 47,32196 → iguais | 2860,90586 → 2956,28722 |
| Anterior full, aprovada | 5,691552 | 44=6,004282, 50=20,683489, 167=6,404803, 231=0,187998 | 33,28057200 | 63,50453 / 41,96755 / 60,78575 → 46,80384 / 27,28277 / 47,23570 | 4291,35868 → 4057,85351 |

| Referência | Microbiana TDN linear → NRC | Microbiana RDP linear → NRC | RUP digestível linear → NRC | Endógena |
|---|---|---|---|---:|
| Anterior full, barata | 2537,682 → 2537,682 | 4349,458 → 4350,604 | 1079,705 → 1078,820 | 157,084 |
| Máxima forragem, barata | 2537,763 → 2537,763 | 4350,048 → 4350,092 | 1079,654 → 1079,612 | 157,084 |
| Meta de MS, barata | 2541,979 → 2541,979 | 4379,469 → 4323,273 | 1076,955 → 1121,071 | 157,084 |
| Menor custo básico, barata | 2546,875 → 2546,875 | 4412,740 → 4292,140 | 1073,822 → 1169,203 | 157,084 |
| Anterior full, aprovada | 3133,837 → 2585,975 | 2862,537 → 2914,434 | 2302,251 → 2245,745 | 157,084 |

A oferta total de PM usa `0,64 × min(TDN, RDP) + RUP digestível + 4,72 × MS`. Entre as quatro candidatas baratas acima, o regime TDN permaneceu ativo nos dois cálculos e o desconto permaneceu 1. Toda a diferença de PM veio da RUP digestível, respectivamente +0,88474, +0,04134, −44,11584 e −95,38136 g/vaca/dia (linear menos NRC). As diferenças nos valores de RDP são reais, mas ocorrem no ramo inativo. Na candidata cara, a troca de RDP para TDN como limitante gerou um erro microbiano metabolizável de +176,99987 g. A decomposição simétrica da troca de ramos atribui +193,60697 g a TDN, −16,60708 g a RDP e, adicionalmente, +56,50531 g à RUP digestível. A proteína endógena é exata para a mesma quantidade de MS. O desconto de TDN da candidata cara é 0,825179, face ao 1,0 congelado. Sua taxa de passagem para concentrados é 9,382859%/h, face a 10,117618%/h na referência. Para as forragens úmidas, a taxa correspondente é 6,280105%/h na candidata e 6,297087%/h na referência. O JSON inclui as taxas de todos os IDs, os fatores das referências, os erros absolutos e relativos e os 14 resíduos de cada vetor.

### Separação entre aproximação, precisão do vetor bruto e arredondamento

- A dieta barata da referência anterior de full tinha déficit de PM de 0,884728 g e excesso de MS de 0,000000140 kg no vetor CBC. A mesma matriz em HiGHS removeu o excesso de MS, mas preservou o déficit de 0,884738 g. Máxima forragem manteve o déficit de aproximadamente 0,04134 g com HiGHS. Fixar as taxas modifica a RUP digestível perto de um piso de PM ativo.
- Menor custo básico e meta de MS tinham **exclusivamente** excesso bruto de MS de 0,000000150 e 0,000000340 kg, com tolerância vigente de 0,000000100 kg. A aproximação de proteína foi conservadora para essas duas dietas. Os vetores obtidos com a mesma matriz em HiGHS passam na etapa bruta e são aprovados depois do reparo existente. Em ambas, os valores positivos entregues pelo CBC são exatamente os valores de HiGHS arredondados a oito algarismos significativos. Isso localiza a divergência na precisão disponível do vetor CBC/PuLP. O experimento não inspecionou o vetor interno antes da saída do CBC. A dieta bruta rejeitada não é elegível ao reparo atual. Seu arredondamento a seis casas agravou o teto de MS para aproximadamente 0,000000930 kg.
- A dieta bruta do SLSQP usada como referência também ilustra a distinção. A candidata quase idêntica do CBC falhou por −0,00002295 g de PM. Em HiGHS a bruta passa, mas o arredondamento a seis casas a derruba e o reparo vigente não encontra resultado. A própria dieta cara selecionada pelo CBC passou a etapa bruta, falhou no Ca após arredondar (−0,00004232 g) e passou após o ajuste de uma unidade da malha, com margem de Ca de +0,00016668 g. 
- No single, no terceiro dia os candidatos ótimos de cada tentativa encostaram no teto aproximado de PM de 4291,358773 g. O primeiro conjunto atingiu entre 4294,01 e 4447,82 g pelo NRC na avaliação original. Os resíduos negativos variaram de cerca de −164,34 a −2,03 g nas três tentativas. A redução de leite baixou os pisos, mas não mudou o teto ancorado nem substituiu a única referência. A Pen esgotou a redução permitida e levantou a exceção antes de chegar à finalização que poderia reaproveitar a dieta anterior.

## Equivalência das restrições e classificação

O código usa o mesmo vetor de custos e os mesmos limites por ID. A auditoria confrontou as oito linhas básicas recompostas com as oito funções NRC. A diferença ficou abaixo de 1e−8 em suas respectivas unidades. Para FDN total, FDN de forragem e gordura, dividiu-se a margem da linha LP por MS positiva, recuperando pontos percentuais. Os mínimos e máximos de FDN total são 25% e 45%, FDN de forragem no mínimo 15% e gordura no máximo 7%. Cálcio e fósforo são g digestíveis calculados pelos métodos originais, por kg de MS de cada alimento. MS é kg/vaca/dia. As matrizes montadas para energia, ambos os limites de PM e a desigualdade que seleciona o ramo microbiano foram verificadas contra as expressões recompostas. Não houve evidência de erro de índice, unidade, sinal ou montagem nessas linhas.

A união das três condições de energia total representa `max(ELman, ELcres, ELlact) >= exigência total` para os coeficientes fixos. Cada caso exige que o componente escolhido atinja o total, sem exigir que seja o maior. Assim, uma dieta pode aparecer em mais de um caso e o conjunto dos três continua correto. Para PM, cada caso impõe o menor total microbiano antes de aplicar o piso vigente e o teto de 1,5 vezes a exigência inicial. A troca do limitante entre a previsão e a avaliação NRC é consequência de mudar os fatores da dieta, com as expressões de mínimo e máximo preservadas na aproximação.

| Categoria | Evidência |
|---|---|
| Aproximação matemática | Desconto de TDN e taxas de passagem da referência podem diferir substancialmente dos da candidata. Os erros mudam de sinal no piso de PM e fazem o ótimo do LP exceder o teto no NRC. |
| Precisão numérica | Duas soluções econômicas corretas para o NRC são perdidas apenas na precisão entregue pelo CBC. O arredondamento a seis casas cria violações adicionais identificáveis em ambos os métodos. |
| Geração e seleção de referências | Priorizar a dieta anterior em single restringe a busca a um único conjunto de fatores. A referência anterior contribuiu para a falha, e sua ausência, por si só, ainda deixou resultados caros nos objetivos avaliados. Midwest e a reexecução de matrizes forneceram contraexemplos mais econômicos. |
| Configuração nutricional e econômica | O piso de PM mudou de 2843,46 para 3119,80 e 2860,91 g. A trajetória SLSQP teve 2867,62 g no terceiro dia. O RuFaS usa condições correntes e suprimentos anteriores para calcular as exigências. O valor de US$ 0,01/kg para as três forragens e os preços mais altos de 44 e 167 amplificam a diferença de custo. |
| Implementação do fluxo | O tratamento de falha de lactação aborta antes da finalização quando se esgota a redução. A auditoria não identificou erro algébrico na formulação dos seis LPs. A validação funciona conforme a regra documentada de exigir aprovação bruta antes de reparar. |

O limite inferior primário permaneceu próximo de US$ 0,28, de 0,278794 para 0,277202 e 0,275871. Ele retira energia e PM, por isso comporta dietas ainda mais baratas. O crescimento do gap de 25,39% para 32,11% e 95,15% veio sobretudo do aumento do custo aprovado. A dieta SLSQP aprovada a US$ 0,369054 no mesmo problema tem gap de 25,25% perante esse limite. A candidata da meta de MS obtida com a mesma matriz custa cerca de US$ 0,369587, gap de 25,36%. Assim, reduzir o custo efetivo não implica atingir a meta de 5%. O experimento anterior com uma vaca e entradas estáticas não exercitava o encadeamento de dietas, as exigências variáveis da baia e os limites da Pen. A estabilidade local naquele cenário não garante estabilidade nessas reformulações.

## Alternativas a avaliar

1. Testar acesso a vetores de maior precisão na interface com CBC e verificar as margens da própria matriz antes de classificar o caso. Avaliar uma correção numérica isolada e auditável somente para discrepâncias certificadas entre a solução e a matriz, sempre revalidando as 14 funções NRC com as tolerâncias atuais.
2. Medir referências menos sensíveis a uma única dieta anterior, incluindo receita compatível ou uma regra de diversidade da MS e da fração de concentrados. Separar adequação como referência de aprovação como dieta. Quantificar o benefício em novos cenários controlados depois de esclarecer a precisão numérica.
3. Auditar separadamente o caminho de encerramento da Pen após a última redução, incluindo o risco de reaplicar automaticamente uma dieta que exceda o teto de MS ou outro requisito do dia. 
4. Se a meta de gap continuar distante de dietas economicamente aceitáveis, investigar relaxações com limites nutricionais comprovados para obter um limite inferior mais informativo. Isso não altera a certificação das dietas ou a definição do gap.

## Reprodução

Com as saídas da CLI anterior disponíveis, na raiz do repositório:

```powershell
py -3.12 -m helpful_scripts.nrc_ration_comparison.cli_isolated_audit
```

O arquivo gerado é `output/nrc_cli_three_day/isolated_audit.json`. Mostra as entradas exatas por tentativa, os resíduos e as dietas brutas, arredondadas e reparadas, os coeficientes, o resultado por referência e as validações das execuções comparáveis. Os tempos de SLSQP incluem a chamada original e os de PuLP incluem a busca do adaptador, ambos medidos fora da simulação. As rotinas de auditoria e HiGHS não entram nesses tempos e não são parte do backend. Nenhuma mudança foi feita nas equações, no código da Pen, nos solvers de produção ou nas tolerâncias.
