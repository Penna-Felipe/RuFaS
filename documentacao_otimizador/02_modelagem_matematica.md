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

## 9. Restrições de fibra em detergente neutro (FDN)

O RuFaS estabelece três restrições relacionadas à concentração de FDN na dieta: limite inferior, limite superior e quantidade mínima de FDN proveniente de forragens.

### Parâmetros

- fᵢ: percentual de FDN do ingrediente i.
- Fmín: concentração mínima de FDN.
- Fmáx: concentração máxima de FDN.
- Fvol: concentração mínima de FDN proveniente de forragens.
- vᵢ: indicador de classificação do ingrediente como forragem, igual a 1 para forragens e 0 para os demais ingredientes.

O indicador vᵢ é um parâmetro constante, e não uma variável de decisão.

### Equações reformuladas

FDN mínima:

Σ (fᵢ − Fmín)xᵢ ≥ 0

FDN máxima:

Σ (fᵢ − Fmáx)xᵢ ≤ 0

FDN de forragens:

Σ (fᵢvᵢ − Fvol)xᵢ ≥ 0

### Análise de linearidade

As equações originais possuem uma divisão pela quantidade total de matéria seca, caracterizando expressões fracionárias dependentes das variáveis de decisão.

A multiplicação de ambos os lados das desigualdades pela matéria seca total permite eliminar o denominador, resultando em restrições lineares equivalentes.

Essa transformação é exata para dietas com matéria seca total estritamente positiva. Não são utilizadas aproximações nutricionais.

### Referências ao código original

Arquivo `ration_optimizer.py`:

- `RationOptimizer.NDF_constraint_lower()`
- `RationOptimizer.NDF_constraint_upper()`
- `RationOptimizer.forage_NDF_constraint()`

Arquivo `nutrition_supply_calculator.py`:

- `NutritionSupplyCalculator.calculate_forage_neutral_detergent_fiber_content()`

Arquivo `animal_module_constants.py`:

- `MINIMUM_RATION_NDF`
- `MAXIMUM_RATION_NDF`
- `MINIMUM_RATION_FORAGE_NDF`

### Implementação desenvolvida

Arquivo `otimizador_alimentar_linear.py`:

- `LinearRationOptimizer._add_ndf_constraints()`
- `LinearRationOptimizer._add_forage_ndf_constraint()`

Os valores nutricionais e os limites são obtidos diretamente das estruturas e constantes originais do RuFaS.

## 10. Restrição de gordura máxima

A restrição de gordura máxima controla a concentração de extrato etéreo da dieta em relação à matéria seca total.

### Parâmetros

- eᵢ: percentual de extrato etéreo do ingrediente i.
- xᵢ: quantidade de matéria seca do ingrediente i.
- Emáx: percentual máximo de gordura permitido pelo RuFaS, correspondente a 7%.

### Equação original

Emáx − (Σ eᵢxᵢ / Σ xᵢ) ≥ 0

### Reformulação linear

Σ eᵢxᵢ ≤ Emáx × Σ xᵢ

Equivalentemente:

Σ (eᵢ − Emáx)xᵢ ≤ 0

### Análise de linearidade

A expressão original apresenta uma divisão pela matéria seca total, que depende das variáveis de decisão.

A multiplicação da desigualdade pela matéria seca total elimina o denominador e produz uma restrição linear equivalente, desde que a matéria seca total seja estritamente positiva.

Não são utilizadas aproximações matemáticas.

### Rastreabilidade

**Código original:**

- `ration_optimizer.py`: `RationOptimizer.fat_constraint()`
- `ration_optimizer.py`: `RationConfig.EE_list`
- `animal_module_constants.py`: `AnimalModuleConstants.MAXIMUM_RATION_FAT`

**Implementação desenvolvida:**

- Arquivo: `otimizador_alimentar_linear.py`
- Método: `LinearRationOptimizer._add_fat_constraint()`
- Identificador da restrição: `Fat_Maximum`

### Validação proposta

Avaliar um cenário convencional, no qual a restrição apresenta folga, e um cenário artificial com elevado teor de gordura, no qual a restrição se torna ativa.

As soluções devem ser verificadas utilizando a função de restrição original do RuFaS.