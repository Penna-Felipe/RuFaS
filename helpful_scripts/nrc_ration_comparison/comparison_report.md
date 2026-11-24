# Relatórios comparativos do RuFaS

O módulo lê exportações `saved_variables_json` com `info_maps` e usa os cadastros apontados pelo `metadata.json` de cada execução. Ele reutiliza o leitor, os nomes de séries e os auxiliares de `cli_three_day.py` e `cli_three_day_summary.py`. A consolidação histórica em `reproduction/midwest_30day/analyze.py` pressupõe quatro lotes e seleciona um arquivo por diretório. A interface abaixo recebe o JSON exato de cada execução, descobre os lotes nas séries exportadas e usa os marcadores de calendário de cada registro.

## Executar e abrir

Use Python 3.12 com as dependências do projeto, inclusive Matplotlib. Execute a partir da raiz do RuFaS. Cada ocorrência de `--run` recebe um rótulo, o resultado e o arquivo de metadados. Informe de duas execuções em diante. A ordem define a base de cada par. Os caminhos abaixo reproduzem o relatório com o JSON manual de cinco referências.

```powershell
$experiment = 'output/nrc_midwest_30day'
py -3.12 -B -m helpful_scripts.nrc_ration_comparison.comparison_report `
  --run slsqp "$experiment/runs/slsqp/1/JSONs/slsqp_saved_variables_json_cli_feeding.txt_24-Nov-2026_Tue_14-15-12.json" "$experiment/inputs/slsqp/1/metadata.json" `
  --run highs3 "$experiment/runs/highs_midwest_3/1/JSONs/full_saved_variables_json_cli_feeding.txt_24-Nov-2026_Tue_14-15-14.json" "$experiment/inputs/highs_midwest_3/1/metadata.json" `
  --run highs5_manual "$experiment/runs/highs_midwest_5/1/JSONs/full_saved_variables_json_cli_feeding.txt_24-Nov-2026_Tue_15-56-18.json" "$experiment/inputs/highs_midwest_5/1/metadata.json" `
  --trace slsqp "$experiment/runs/slsqp/1/attempts.jsonl" `
  --trace highs3 "$experiment/runs/highs_midwest_3/1/attempts.jsonl" `
  --console slsqp "$experiment/runs/slsqp/1/console.log" `
  --console highs3 "$experiment/runs/highs_midwest_3/1/console.log" `
  --output output/nrc_comparison_report_30day_repro
Invoke-Item 'output/nrc_comparison_report_30day_repro/index.html'
```

Use um novo diretório para cada geração. Para abrir o relatório já gerado, execute `Invoke-Item 'output/nrc_comparison_report_30day_summary/index.html'`. O navegador abre o HTML diretamente. A página resumida incorpora os cinco gráficos, os dados dos seletores de dia e lote, o JavaScript e o estilo. Abra o relatório técnico pelo link no topo ou em detailed_report.html. Mantenha os arquivos no mesmo diretório para acessar os CSVs e os 22 PNGs pelos links. Use `--trace` e `--console` somente para auxiliares da mesma execução. Os auxiliares instrumentados de HiGHS com cinco referências pertencem à execução das 14h15 e foram omitidos na comparação que usa a exportação manual das 15h56.

```powershell
py -3.12 -B -m pytest -q -p no:cacheprovider helpful_scripts/nrc_ration_comparison/test_comparison_report.py
```

## Arquivos e interpretação

| Arquivo | Conteúdo |
|---|---|
| `index.html` | Resumo em cinco seções, com seleção de dia e lote e lactação selecionada inicialmente |
| `detailed_report.html` | Relatório técnico com toda a auditoria, as tabelas e os 22 gráficos |
| `*.png` | Figuras individuais em 220 dpi |
| `summary.csv`, `daily_herd.csv`, `daily_pens.csv` | Resumo e séries de custo, produção, MS fornecida e animais |
| `composition.csv`, `ingredient_costs.csv` | Dieta registrada, quantidades fornecidas e participação no custo por ID |
| `herd_deltas.csv`, `pen_deltas.csv`, `ingredient_deltas.csv` | Diferenças calculadas como comparação menos base. O percentual usa o valor da base |
| `nutrition.csv` | Meta, oferta, limite efetivo quando identificável, margem, tolerância, auditoria e valor original do avaliador |
| `attempts.csv` | Tentativas, sucessos registrados, validação linear, tempos, solver, referências, limite inferior e gap |
| `purchases.csv` | Eventos de aquisição exportados pelo FeedManager, quando disponíveis |
| `integrity.csv`, `provenance.json` | Compatibilidade das entradas fornecidas, hashes, lacunas e verificações de consistência |

Os custos usam os preços da entrada de cada execução em US$/kg MS. O custo fornecido multiplica o preço pela quantidade aplicada por lote. O custo formulado usa a ração por animal e é conferido com o custo registrado nas tentativas bem-sucedidas. O custo por kg de leite do rebanho inclui todos os lotes. As quantidades em matéria natural são estimadas usando o teor de MS do cadastro. Aquisições são lançamentos próprios do FeedManager. Em um arquivo com cobertura desconhecida, um dia sem lançamento fica vazio. Nos três JSONs deste relatório, a aquisição efetiva está indisponível.

As séries são alinhadas por data civil e, por lote, também por ID e grupo. Duplicatas nas séries diárias ou nas chaves de tentativa são excluídas e assinaladas. Comparações acumuladas exigem períodos alinhados. Para lotes, o leite vem dos registros por vaca e baia. Para o rebanho, o total do reporter é a fonte principal. Compare tempos qualitativamente quando a instrumentação diferir.

## Auditoria da execução manual

- **Primeira dieta de lactação.** A meta de DMI foi 25,8746607535 kg MS/animal/dia. A faixa admitida de ±30% foi de 18,1122625275 a 33,6370589796 kg. A dieta de 33,637059 kg excedeu o teto em aproximadamente 2,04 × 10⁻⁸ kg após arredondamento. A tolerância absoluta da validação linear é 10⁻⁷ kg para os limites de DMI, e o registro da tentativa confirma aprovação NRC. A oferta ultrapassou a meta em 7,762398 kg. A FDN total também ficou junto ao limite superior de 45% da MS.
- **Semântica do AnimalModuleReporter.** Para DMI, proteína metabolizável e FDN total, o avaliador original reporta a distância assinada ao limite quando a oferta sai da faixa e zero dentro da faixa. No primeiro dia manual, a oferta de proteína metabolizável foi 2.889,524 g, frente à meta de 2.843,457 g, apesar de o avaliador reportar zero. Para cálcio e fósforo o relatório usa a oferta digestível. Os valores exportados em kg são convertidos para g antes de comparar com a exigência. Os limites reconstruídos usam as constantes da revisão local e o contexto disponível. Em particular, os limites que dependem das exigências iniciais podem ficar em branco em dias com tentativas adicionais.
- **Dias 8 e 15.** O JSON contém uma formulação de lactação aprovada em cada índice de simulação de 0 a 29, incluindo 8 (7 de junho, juliano 158) e 15 (14 de junho, juliano 165). O oitavo e o décimo quinto dia na contagem iniciada em 1 também estão presentes (6 e 13 de junho). A origem da omissão na tabela mencionada é indeterminada a partir do JSON.
- **Diagnósticos.** PuLP registra o resultado do adaptador e sua validação NRC. O status do LP vencedor pode vir do rastreamento vinculado. No SLSQP, o sucesso registrado, a avaliação legada e a checagem NRC externa do rastreamento têm significados distintos. A referência vencedora `previous_ration` indica uma nova formulação que explorou a dieta anterior como referência. O reaproveitamento após falha usa evidência de log da execução.

As três execuções cobrem os dias julianos 150–179 de 2013, com semente 42. As entradas fornecidas de configuração, manejo e preços são compatíveis entre os três pares, após excluir as opções de backend da comparação de manejo. Os hashes documentam os arquivos disponíveis no momento do relatório. As trajetórias de leite e de exigências do SLSQP e do HiGHS diferem após o início. As diferenças acumuladas são descritivas, sem atribuição causal.

