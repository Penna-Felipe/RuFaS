# Experimento NRC de três dias pela CLI do RuFaS

## Cenário e reprodução

O experimento executa a simulação `animals_only` pela CLI, com as rotinas reais de alimentação, lactação e dinâmica do rebanho. Usa os dias julianos 150, 151 e 152 de 2013, a população de exemplo `animal_population.json`, a configuração `freestall`, a semente 42 e reformulação diária. As quatro baias estavam ocupadas na primeira formulação, com 8 animais em CALF, 82 em GROWING, 20 em CLOSE_UP e 76 em LAC_COW. A auditoria encontrou os mesmos IDs e as mesmas baias das vacas no primeiro dia dos quatro métodos.

O script cria cópias sob `output/`. O cardápio deriva do Midwest. Os IDs 301 e 302 ficaram de fora por ausência no NRC. Foram acrescentados 167 e 231 para oferta proteica e mineral, com preços experimentais de US$ 0,37 e US$ 0,60 por kg de matéria seca. Os demais preços são do exemplo. O pré-teste verifica o cadastro NRC, a unidade, a matéria seca, os limites individuais e o cardápio de cada baia. O NRC e o próprio RuFaS calculam os requisitos durante a execução. O arquivo `inputs/preflight.json` identifica ingredientes, composições e fontes.

Na raiz do repositório, em PowerShell, com o ambiente RuFaS e o extra `linear_ration` instalados:

```powershell
$script = 'helpful_scripts/nrc_ration_comparison/cli_three_day.py'
$base = 'output/nrc_cli_repro'
py -3.12 $script --base $base prepare
py -3.12 $script --base $base slsqp
py -3.12 $script --base $base single
py -3.12 $script --base $base full
py -3.12 $script --base $base adaptive_gap
```

Cada execução arquiva a invocação direta de `main.py` e o tempo de parede em `run.json`. Use uma pasta nova para cada repetição. O comando `single` encerra com falha neste cenário. O TaskManager registrou a exceção e a CLI original devolveu código 0. O script de experimento verifica também o marcador de conclusão.

A extração diagnóstica roda separadamente, sem alterar as decisões do modelo. Cada tentativa é gravada logo após o registro original. A captura do pool de saída mantém acesso aos dias completos caso o RuFaS encerre antes de exportar o JSON padrão. Os tempos comparativos vêm das execuções diretas, salvo os tempos por tentativa do `single`, recuperados da execução diagnóstica.

```powershell
$trace = 'output/nrc_cli_repro_trace'
py -3.12 $script --base $trace prepare
foreach ($method in @('slsqp', 'single', 'full', 'adaptive_gap')) {
    $run = "$trace/runs/$method"
    New-Item -ItemType Directory -Path $run -Force | Out-Null
    $env:RUFAS_EXPERIMENT_TRACE = "$run/attempts.jsonl"
    py -3.12 helpful_scripts/nrc_ration_comparison/cli_three_day_trace.py -g -v logs -p "$trace/inputs/$method/task_manager.json" -o $run -l "$run/logs"
}
py -3.12 helpful_scripts/nrc_ration_comparison/cli_three_day_summary.py --base $base --diagnostics $trace
```

O resumo JSON contém as dietas por ID, as ofertas e exigências com unidades, os registros por tentativa e os custos por baia. Cada `attempts.jsonl` preserva a referência e as 14 restrições avaliadas nas candidatas ótimas do PuLP. O experimento usou Python 3.12.10, PuLP 3.3.2 e SciPy 1.18.1.

## Resultados observados

| Configuração | Dias completos | Custo aplicado à lactação, US$ | Custo aplicado aos outros grupos, US$ | Leite, kg | CLI, s | Chamadas PuLP / SLSQP |
|---|---|---:|---:|---:|---:|---:|
| SLSQP | 150–152 | 88,23 | 33,20 | 9.659,51 | 37,57 | 0 / 9 |
| PuLP single | 150–151 | 440,18 | 21,02 | 6.412,15 | 33,42 | 50 / 6 |
| PuLP full | 150–152 | 504,56 | 33,80 | 9.659,51 | 47,84 | 192 / 6 |
| PuLP adaptive_gap | 150–152 | 504,56 | 33,80 | 9.659,51 | 29,55 | 192 / 6 |

O custo diário da formulação é a soma das quantidades por animal multiplicadas pelos preços em US$/kg de matéria seca. O custo da alimentação aplicada usa os totais diários por baia com os mesmos preços. A lotação pode mudar entre formulação e alimentação, inclusive dentro do dia. Os dias completos são a base dos custos aplicados e do leite. `animals_only` trata os pedidos atendidos como alimento comprado para o fluxo físico e de emissões. O cenário não apura estoque, pagamentos ou custo efetivo de aquisição.

### Lactação por dia

| Método | Dia | MS, kg/vaca | Dieta, US$/vaca | Aplicado, US$ | Leite, kg | Limite inferior, US$/vaca | Gap | Referência escolhida |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| SLSQP | 150 | 33,6371 | 0,36630 | 28,21 | 3.202,69 | — | — | — |
| SLSQP | 151 | 33,4558 | 0,40558 | 31,63 | 3.228,72 | — | — | — |
| SLSQP | 152 | 33,2806 | 0,36399 | 28,39 | 3.228,10 | — | — | — |
| single | 150 | 33,6371 | 0,37364 | 28,77 | 3.202,69 | 0,27879 | 25,39% | minimum_cost |
| single | 151 | 33,4558 | 5,27451 | 411,41 | 3.209,47 | 0,27591 | 94,77% | previous_ration |
| full e adaptive_gap | 150 | 33,6371 | 0,37364 | 28,77 | 3.202,69 | 0,27879 | 25,39% | minimum_cost |
| full e adaptive_gap | 151 | 33,4558 | 0,40832 | 31,85 | 3.228,72 | 0,27720 | 32,11% | target_dmi |
| full e adaptive_gap | 152 | 33,2806 | 5,69155 | 443,94 | 3.228,10 | 0,27587 | 95,15% | previous_ration |

No último dia dos cenários completos, SLSQP utilizou 0,346501 kg MS do ID 23, 6,869162 do ID 50 e 26,064910 do ID 110 por vaca. `full` e `adaptive_gap` utilizaram 6,004282 do ID 44, 20,683489 do ID 50, 6,404803 do ID 167 e 0,187998 do ID 231. O relatório JSON inclui a composição de todas as baias e dias.

`full` e `adaptive_gap` avaliaram 4, 5 e 5 referências. Foram 60, 66 e 66 chamadas por dia, incluindo a relaxação de custo, a geração das referências e os seis casos de cada referência distinta. Como nenhum gap atingiu 5%, ambos fizeram a mesma busca. Os tempos das tentativas de lactação foram 0,275, 0,147 e 0,368 s no SLSQP, 3,207, 5,373 e 5,440 s em `full` e 1,687, 1,725 e 1,670 s em `adaptive_gap`. O cronômetro das tentativas PuLP inclui geração, resolução, validação e reparo. A diferença de tempo entre estratégias com o mesmo número de chamadas é uma observação de uma execução por configuração.

### Validação, aplicação e falha

- As quantidades aprovadas pelo PuLP foram aplicadas exatamente por ID, inclusive após os reparos. O primeiro dia recebeu dieta anterior vazia. As tentativas seguintes receberam a dieta aplicada no dia anterior. O fluxo de bezerras usou a receita direta e GROWING e CLOSE_UP usaram SLSQP por escopo. A tentativa da baia LAC_COW manteve PuLP depois de cada rejeição.
- `single` teve 2 tentativas aprovadas e 4 rejeitadas. Dos seus 36 casos LP nutricionais, 5 foram aprovados, 25 eram ótimos do LP e foram rejeitados na validação, e 6 eram inviáveis no LP. `full` e `adaptive_gap` tiveram, cada um, 3 tentativas aprovadas. Dos 84 casos LP nutricionais de cada método, 11 foram aprovados, 67 rejeitados pelo NRC e 6 inviáveis. Esses totais contam casos, inclusive candidatos repetidos entre regimes.
- No segundo dia, `single` recebeu a dieta anterior como referência, rejeitou a primeira tentativa e aprovou uma dieta de US$ 5,27451 após a redução de leite prescrita pelo fluxo de produção. O reparo removeu a violação do teto de MS. No terceiro dia, as três tentativas exploraram somente a nova dieta anterior. Todos os ótimos LP desse dia excederam o teto de proteína metabolizável na avaliação original, com resíduos entre aproximadamente −164,34 e −2,03 g/vaca/dia. A rotina `Pen._reduce_on_lactation_failure()` lançou a exceção de limite de redução de leite antes de `_finalize_ration_outcome()`. Isso impediu que o fluxo chegasse à reutilização da dieta anterior. 
- No terceiro dia de `full` e `adaptive_gap`, algumas candidatas de US$ 0,36–0,38/vaca foram rejeitadas por proteína abaixo do mínimo ou por excesso de MS já no vetor bruto. O reparo existente exige aprovação do vetor bruto. A dieta de US$ 5,69155 foi aprovada após o reparo do arredondamento de cálcio. Seus resíduos de cálcio e MS superior foram +0,0001667 g/vaca/dia e +0,0000000698 kg MS/vaca/dia. As demais margens e as dietas rejeitadas estão no registro de tentativas.
- O SLSQP convergiu nas três formulações de lactação. A verificação diagnóstica da dieta já aplicada detectou dois déficits pequenos de proteína (−0,000308 e −0,000220 g/vaca/dia) e um excesso de MS (+0,000000930 kg MS/vaca/dia) sob as mesmas tolerâncias usadas para aprovar PuLP. O avaliador legado também sinalizou gordura nas dietas, inclusive nas dietas PuLP aprovadas. Seu cálculo retorna a margem positiva em relação ao máximo de gordura e o relatório exige margem igual a zero. Esse indicador legado deve ser interpretado separadamente dos resíduos do otimizador.
- A oferta NRC por animal registrada na simulação e a validação do otimizador usam níveis diferentes de agregação. Por exemplo, no último dia de `full`, a média das ofertas individuais foi 46,622 Mcal de manutenção, 27,116 de crescimento, 47,099 de lactação e 4.058,73 g de proteína metabolizável, frente à exigência média reportada de 2.860,91 g. O otimizador calcula os resíduos com as condições agregadas no `RationConfig`.

O experimento demonstrou execução diária e aplicação de dietas aprovadas nas estratégias `full` e `adaptive_gap`, e expôs a interrupção antecipada do `single` em uma sequência real de reformulações. A meta de gap ficou distante nos três dias e o custo alto do último dia merece ser interpretado juntamente com as rejeições nutricionais e numéricas. A duração curta, os preços ilustrativos, uma semente e uma execução cronometrada por cenário limitam comparações econômicas e computacionais.
