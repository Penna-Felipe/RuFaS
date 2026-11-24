# Arquivos de reprodução e apresentação

Os roteiros nesta pasta foram preservados a partir dos diretórios de saída. As tabelas CSV da trajetória de 30 dias são cópias dos arquivos validados. As séries têm 90 registros, um por cenário e dia. As colunas de gap representam frações, que podem ser exibidas como percentuais.

## Trajetória de 30 dias

Execute a partir da raiz do repositório, com o extra `linear_ration_highs` instalado e o cenário original em `output/nrc_cli_three_day/`. Use um checkout de reprodução em que `output/nrc_midwest_30day/` esteja livre. O roteiro exige um diretório novo para impedir sobrescrita.

```powershell
py -3.12 -m helpful_scripts.nrc_ration_comparison.reproduction.midwest_30day.run_experiment
py -3.12 -B helpful_scripts/nrc_ration_comparison/reproduction/midwest_30day/analyze.py
```

O primeiro comando inicia três processos concorrentes. O segundo apenas lê as saídas e escreve os CSVs e o resumo JSON no diretório do experimento. Para uma análise sem simulação, use somente o segundo comando com as saídas arquivadas no caminho esperado.

## Outros roteiros preservados

- `highs_three_day/trace_highs.py` e `analyze.py` preservam a instrumentação e a consolidação do piloto nutricional de três dias. O comparativo replicado posterior usa `cli_solver_consolidation.py`, que reúne preparação, execução e consolidação.
- `reference_budgets.py` preserva o roteiro da comparação dos orçamentos de 1, 2, 3 e 5 referências. Execute como módulo a partir da raiz, com `output/nrc_reference_solver_budgets/` livre e as entradas arquivadas do cenário original. A cópia remove apenas a linha que salvava o próprio código a partir de uma variável de ambiente.
- `artifacts_local.tsv` lista insumos e resultados a manter fora do Git. `version_files.tsv` lista os arquivos a incluir na revisão deste ciclo.
