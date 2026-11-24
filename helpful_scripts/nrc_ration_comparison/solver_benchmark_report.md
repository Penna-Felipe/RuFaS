# Precisão do CBC, HiGHS e referências externas no NRC

## Método e ambiente

O experimento reutilizou os modelos de produção para capturar as seis matrizes de cada referência. Os mesmos custos, limites, exigências, coeficientes fixos e regimes foram entregues às seis interfaces. Nas 15 tentativas da CLI, congelaram-se as referências efetivamente avaliadas na reprodução anterior, inclusive o orçamento de uma referência do single. Nas 12 formulações históricas, foram geradas uma vez com CBC as quatro referências básicas disponíveis em produção, com descarte das duplicadas. A busca histórica anterior já incluía Midwest. Aqui ela entra apenas no braço adicional, para medir seu efeito sobre a busca de produção. O conjunto principal contém 552 casos, 288 da CLI e 264 históricos.

Foram feitas cinco repetições por interface e caso, alternando a ordem. Os tempos incluem a transferência do modelo, a resolução e a leitura do vetor, incluindo arquivo e processo quando aplicáveis. Excluem geração de referências, cálculo dos coeficientes, montagem original da matriz, validação NRC e reparo. As repetições preservaram os vetores e os estados em todos os 552 casos de cada interface. O ambiente foi Windows, Python 3.12.10, PuLP 3.3.2, CBC 2.10.3, highspy 1.16.0 e SciPy 1.18.1 com HiGHS interno 1.12.0. PuLP/HiGHS usou uma thread e os demais parâmetros padrão, com tolerâncias primal e dual de 1e−7. SciPy usou `linprog(method="highs")`, com parâmetros padrão iguais aos da auditoria anterior. O instalador de highspy foi direcionado à pasta experimental.

## Onde a precisão se perde

- **Modelo.** A interface CBC do PuLP escreve MPS com nomes normalizados e formato `%.12e`, com 13 algarismos significativos. Na releitura dos 552 arquivos, os desvios máximos absolutos foram 4,96e−11 nos coeficientes das linhas, 4,86e−10 no termo independente e 1,24e−13 no objetivo, sem diferenças nos limites. Um controle adicional passou ao HiGHS exatamente os valores decimais do MPS. Os estados e a aprovação final permaneceram iguais aos do HiGHS com os valores em memória nos 552 casos. [Exportador MPS do PuLP](https://github.com/coin-or/pulp/blob/3.3.2/pulp/mps_lp.py)
- **Solução.** CBC foi chamado com `-solve -printingOptions all -solution`. Na variante experimental, a mesma invocação gravou também `-saveSolution`. O arquivo binário guarda inteiros de dimensão e dados `double`, inclusive as atividades primais das colunas. O pequeno controle de uma variável mostrou 32,666667 no texto e 32,666666666666664 no binário do mesmo processo. Nos **466 LPs ótimos**, as soluções do CBC padrão coincidiram com o texto desse processo e com o binário arredondado a oito algarismos significativos. A maior diferença em uma quantidade foi **4,984e−7 kg**, acima da tolerância absoluta de MS do NRC de 1e−7 kg. [CBC 2.10.3](https://raw.githubusercontent.com/coin-or/Cbc/releases/2.10.3/Cbc/src/CbcSolver.cpp)
- **Leitura.** `readsol_MPS()` converte os números textuais com `float` e reverte o mapeamento dos nomes. A informação já foi perdida na gravação. Na API direta `pulp.HiGHS`, o modelo entra por chamadas a `addCol/addRow` e os valores primais saem de `getSolution()`, em memória. [Interface CBC do PuLP](https://github.com/coin-or/pulp/blob/3.3.2/pulp/apis/coin_api.py) · [Interface HiGHS do PuLP](https://github.com/coin-or/pulp/blob/3.3.2/pulp/apis/highs_api.py)
- **Opções do CBC.** A configuração instalada tem tolerâncias primal e dual de 1e−7. Testar `primalTolerance 1e-9` e `dualTolerance 1e-9` preservou integralmente os vetores de texto e as decisões da configuração padrão. `outputFormat 4` também produziu os mesmos vetores. Essa opção afeta exportação, inclusive de modelo ou base, e não aumentou a resolução do comando `solution` nesta versão. A saída binária demonstrou maior precisão com as tolerâncias padrão. A alternativa exige uma interface que leia o binário ou obtenha os valores diretamente de uma API validada. [Opções do CBC](https://github.com/coin-or/Cbc/blob/master/doc/cbc-parameters.md)

## Resultados com as mesmas referências

| Interface | LPs ótimos / inviáveis | Brutos aprovados | Aprovados a 6 casas sem reparo, entre os brutos válidos | Reparos aprovados | Aprovados finais | Mediana por LP, ms | P90 das medianas, ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| CBC padrão, texto | 466 / 86 | 187 | 114 | 54 | 168 | 26,57 | 38,21 |
| CBC tolerâncias 1e−9, texto | 466 / 86 | 187 | 114 | 54 | 168 | 26,33 | 38,35 |
| CBC outputFormat 4, texto | 466 / 86 | 187 | 114 | 54 | 168 | 26,37 | 39,07 |
| CBC, binário | 466 / 86 | 264 | 113 | 110 | 223 | 54,07 | 81,91 |
| PuLP/HiGHS 1.16 | 466 / 86 | 264 | 113 | 110 | 223 | 2,15 | 2,46 |
| SciPy/HiGHS 1.12 | 466 / 86 | 264 | 113 | 110 | 223 | 4,46 | 5,42 |

As três interfaces com maior precisão aprovaram os mesmos casos. Elas recuperaram **56** candidatas rejeitadas pelo CBC padrão e perderam uma anteriormente aprovada, saldo de **55**. Das 56 recuperadas, 55 tinham falha bruta classificada como numérica e uma falhava no arredondamento. O caso perdido estava na trajetória SLSQP no dia 152, referência máxima forragem, regime crescimento/RDP. Os vetores brutos passaram nas três interfaces. O cálcio ficou abaixo da tolerância após arredondar, e o reparo aprovou apenas a saída textual. A melhor dieta dessa formulação veio de outro caso.

O conjunto principal manteve 23/27 formulações aprovadas com qualquer interface. O vetor mais preciso reduziu o melhor custo em oito das 23 e manteve o custo nas outras 15, com limiar de comparação de US$ 1e−9. Nas tentativas da CLI, as aprovações finais por caso passaram de 39 para 67. Nos cenários históricos, de 129 para 156. Os custos no terceiro dia da trajetória full foram US$ 5,691552 com a saída textual e **US$ 0,369587** com a saída binária ou HiGHS, com a referência meta de MS. A aprovação exigiu o reparo existente.

As somas das cinco repetições, cada uma sobre 552 LPs, ficaram entre 17,52 e 21,36 s no CBC padrão, 36,62 e 40,48 s no leitor binário experimental, 1,17 e 1,27 s no PuLP/HiGHS e 2,47 e 2,70 s no SciPy/HiGHS. A vantagem de tempo do PuLP/HiGHS mede a interface e a resolução neste equipamento, incluindo o custo de iniciar o CBC e acessar arquivos. O leitor binário escreveu as duas saídas, tanto para verificar o status quanto para parear os vetores. Esses tempos não estimam o desempenho da simulação ou do adaptador integral com geração de referências.

### Falhas ainda presentes

Das 466 soluções LP ótimas em cada interface de maior precisão, 202 continuaram com falha bruta por aproximação e 41 passaram no vetor bruto, mas ficaram sem solução aprovada após arredondamento e reparo. Os outros 86 casos são inviáveis na respectiva matriz LP. A contagem de casos inclui regimes que repetem vetores. As 15 tentativas da CLI incluem trajetórias com entradas iguais ou semelhantes.

A classificação comparou os resíduos NRC com os resíduos de energia e proteína calculados com os coeficientes fixos na mesma candidata. Quando somente o NRC falha, a aproximação cruzou a fronteira. Quando ambos falham, verificou-se se o desvio NRC desfavorável acrescentou mais do que a tolerância. As restrições exatamente lineares com desvio bruto foram classificadas como numéricas. Permanecem os erros de desconto de TDN e de passagem que podem alterar a energia, a RUP digestível, o ramo microbiano ativo e a proteína total. Resolver a matriz com maior precisão melhora a satisfação da matriz representada, e os resíduos originais continuam indispensáveis.

## Efeito isolado de referência externa

Testou-se a receita Midwest adaptada como uma sexta referência quando a busca já continha cinco, ou como referência adicional depois do single. Essa extensão foi exclusivamente experimental. A receita foi normalizada à MS-alvo com os cinco ingredientes compartilhados. Os IDs 301 e 302, que somavam 28,48% da receita original, ficaram de fora. Intermountain, Nordeste e Sudoeste tinham IDs positivos fora dos cardápios e foram rejeitados como receitas integrais. O arquivo sem alimentos não tinha proporções. Os dois braços mantiveram ingredientes, preços, exigências e solver. Nenhuma solução do SLSQP entrou como referência.

| Solver fixo | Aprovação antes → depois | Formulações recuperadas | Formulações que já passavam e ficaram mais baratas | Casos aprovados entre os 162 LPs adicionais |
|---|---:|---:|---:|---:|
| CBC padrão | 23/27 → 27/27 | 4 | 7 | 50 |
| PuLP/HiGHS | 23/27 → 27/27 | 4 | 4 | 69 |

No CBC do dia 152 da trajetória full, Midwest substituiu US$ 5,691552 por US$ 0,406778. Com HiGHS, a melhor referência continuou sendo a meta de MS, a US$ 0,369587. Na primeira tentativa single desse dia, Midwest recuperou uma dieta a US$ 0,406778 com ambos os solvers, e nas duas tentativas reduzidas recuperou dietas a US$ 0,393577 e US$ 0,387861. As últimas duas são comparações condicionais com exigências arquivadas. Aceitar a primeira dieta teria alterado a trajetória e evitado essas duas tentativas. Em um cenário histórico ilustrativo, CBC mais Midwest reduziu US$ 6,737873 para US$ 0,367156. As melhorias nos três cenários de preço de mercado com soja ocorreram nos dois solvers, com reduções de aproximadamente US$ 0,17 a US$ 0,38.

## Exceção da Pen e reutilização

A inspeção de `git show HEAD:RUFAS/biophysical/animal/pen.py` no commit local `41e849aa4` confirmou que o fluxo anterior à integração já chamava `_reduce_on_lactation_failure()` dentro da tentativa. A exceção de limite de redução interrompe o retorno para `_finalize_ration_outcome()`, onde o fluxo pode conservar a dieta anterior. No single do dia 152, conservar a dieta anterior teria excedido o teto de matéria seca em **0,175181 kg/vaca** com ou sem redução de leite. Ela também era deficiente em Ca por 0,042024 g/vaca na primeira tentativa. Na última, a margem de Ca já era positiva. A proteína permaneceria dentro do teto por 7,66 g/vaca. No dia 151, a dieta anterior também falhava no piso de proteína e no teto de MS, inclusive depois da redução. Reutilizar a dieta asseguraria disponibilidade imediata, com violações NRC mensuráveis. O comportamento da Pen ficou intacto.

## Recomendação e reprodução

O próximo piloto mais promissor é **PuLP/HiGHS direto para os casos nutricionais, com uma referência externa compatível disponível quando as referências básicas falharem**. O benefício numérico foi confirmado pelo próprio CBC binário. Midwest recuperou as quatro formulações sem dieta aprovada que permaneceram após a troca de interface. Vale preservar a geração de referências e o limite inferior durante o primeiro piloto para atribuir os efeitos. A validação após a troca integral, com o novo solver também no gerador e no cálculo do limite, é uma etapa separada. O CBC binário é uma alternativa diagnóstica quando a dependência highspy for indesejada, com custo de interface observado maior e necessidade de contrato estável para o formato.

Antes de qualquer regra de reutilização na Pen, a dieta anterior deve ser reavaliada com as exigências vigentes e um caso de falha após a última redução precisa ser testado explicitamente. Para os 202 casos ainda rejeitados por aproximação, testar referências independentes representativas e avaliar os resíduos do NRC continua sendo necessário. As tolerâncias nutricionais e o reparo de seis casas foram os existentes em todos os braços.

Na raiz, com a saída da auditoria isolada anterior e o ambiente RuFaS instalados:

```powershell
py -3.12 -m pip install --no-deps --target output/nrc_solver_benchmark/deps highspy==1.16.0
$env:PYTHONPATH = 'output/nrc_solver_benchmark/deps'
py -3.12 -m helpful_scripts.nrc_ration_comparison.solver_benchmark --runs 5
py -3.12 -m helpful_scripts.nrc_ration_comparison.solver_benchmark --mps-check
```

`output/nrc_solver_benchmark/results.json` contém cada matriz e seu hash, dieta, estado, tempos, custos, resíduos lineares e as 14 funções NRC para os vetores bruto, arredondado e reparado quando aplicável. `mps_precision_control.json` contém o controle de coeficientes serializados. Os resultados excluem qualquer simulação nova. As alterações ficaram nos scripts e neste relatório experimental.
