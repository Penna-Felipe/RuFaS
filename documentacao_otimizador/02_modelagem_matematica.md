# Modelagem matemática do otimizador alimentar linear

## 1. Objetivo

Desenvolver um modelo de programação linear para a formulação de dietas de menor custo no RuFaS, utilizando PuLP como biblioteca de modelagem matemática e HiGHS como solver.

A implementação reaproveita as estruturas de dados, as exigências nutricionais e as propriedades dos alimentos existentes no simulador.

## 2. Conjunto de ingredientes

Seja I o conjunto de ingredientes disponíveis para a formulação da dieta de determinada baia.

Cada ingrediente é identificado pelo atributo `rufas_id` fornecido pelo RuFaS.

## 3. Parâmetros

| Símbolo | Descrição | Origem |
|---|---|---|
| cᵢ | Preço do ingrediente i | `RationConfig.price_list` |
| lᵢ | Quantidade mínima do ingrediente i | `RationConfig.feed_minimum_list` |
| uᵢ | Quantidade máxima do ingrediente i | `RationConfig.feed_maximum_list` |

## 4. Variáveis de decisão

A variável contínua xᵢ representa a quantidade de matéria seca do ingrediente i, expressa em kg por animal por dia.

Cada ingrediente disponível possui uma variável de decisão correspondente.

## 5. Função objetivo

Minimizar:

Z = Σ cᵢ × xᵢ

A função objetivo minimiza o custo total da dieta.

**Referência no código original:**

- Arquivo: `RUFAS/biophysical/animal/ration/ration_optimizer.py`
- Classe: `RationOptimizer`
- Método: `objective()`

**Análise de linearidade:**

A função objetivo original é linear em relação às variáveis de decisão, uma vez que os preços dos ingredientes são parâmetros constantes durante a otimização.

Portanto, sua representação em programação linear não exige aproximações.

## 6. Limites de inclusão dos ingredientes

Cada variável deve respeitar:

lᵢ ≤ xᵢ ≤ uᵢ

**Referência no código original:**

- Classe: `RationOptimizer`
- Método: `_build_bounds()`

Os limites são implementados diretamente nos atributos `lowBound` e `upBound` das variáveis do PuLP.

Nesta etapa, são considerados somente os limites convencionais dos ingredientes. Os limites associados às dietas definidas pelo usuário serão tratados posteriormente.

## 7. Estado atual do modelo

A implementação inicial contempla:

- Variáveis de decisão contínuas.
- Limites de inclusão dos ingredientes.
- Função objetivo de minimização de custo.
- Resolução do modelo utilizando HiGHS.
- Recuperação do status, das quantidades e do custo.

As restrições nutricionais serão adicionadas progressivamente.

O modelo inicial não representa uma dieta nutricionalmente completa e não deve ser utilizado para alimentação dos animais.

## 8. Restrições de consumo de matéria seca (DMI)

As restrições de consumo de matéria seca estabelecem os limites inferior e superior da quantidade total de alimentos fornecidos ao animal, em kg de matéria seca por animal por dia.

### 8.1. Parâmetros

| Símbolo | Descrição | Origem no RuFaS |
|---|---|---|
| D | Exigência atual de matéria seca | `animal_requirements.dry_matter` |
| D₀ | Exigência inicial de matéria seca | `initial_dry_matter_requirement` |
| α | Fração de tolerância | `dmi_constraint_fraction` |
| xᵢ | Quantidade do ingrediente i | Variável de decisão |

### 8.2. Restrição inferior

Equação original:

Σ xᵢ − D(1 − α) ≥ 0

Representação em programação linear:

Σ xᵢ ≥ D(1 − α)

### 8.3. Restrição superior

Equação original:

D₀(1 + α) − Σ xᵢ ≥ 0

Representação em programação linear:

Σ xᵢ ≤ D₀(1 + α)

### 8.4. Análise de linearidade

As duas restrições são lineares em relação às variáveis de decisão. Os parâmetros D, D₀ e α são conhecidos e mantidos constantes durante cada resolução do problema.

A reformulação consiste exclusivamente na reorganização algébrica das desigualdades originais, preservando a região viável definida pelas restrições de matéria seca.

Não são realizadas aproximações matemáticas.

### 8.5. Rastreabilidade da implementação

**Arquivo original:** `RUFAS/biophysical/animal/ration/ration_optimizer.py`

**Métodos originais:**

- `RationOptimizer.DMI_constraint_lower()`
- `RationOptimizer.DMI_constraint_upper()`

**Arquivo desenvolvido:** `RUFAS/biophysical/animal/ration/otimizador_alimentar_linear.py`

**Método desenvolvido:** `LinearRationOptimizer._add_dmi_constraints()`

**Identificadores das restrições no PuLP:**

- `DMI_Minimum`
- `DMI_Maximum`

### 8.6. Observações

O limite inferior utiliza a exigência atual, enquanto o limite superior utiliza a exigência inicial. Essa distinção foi preservada para garantir equivalência com a implementação original.

A tolerância é obtida diretamente do RuFaS, sem adoção de um percentual fixo no novo otimizador.