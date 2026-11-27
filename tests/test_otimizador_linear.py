from types import SimpleNamespace
import numpy as np

from RUFAS.biophysical.animal.ration.otimizador_alimentar_linear import (
    LinearRationOptimizer,
)

from RUFAS.biophysical.animal.ration.ration_optimizer import (
    RationOptimizer,
)

from RUFAS.data_structures.feed_storage_to_animal_connection import (
    FeedComponentType,
)

feeds = [
    SimpleNamespace(
        rufas_id=18,
        NDF=12.0,
        EE=4.0,
        feed_type=FeedComponentType.CONC,
    ),
    SimpleNamespace(
        rufas_id=44,
        NDF=15.0,
        EE=2.0,
        feed_type=FeedComponentType.CONC,
    ),
    SimpleNamespace(
        rufas_id=50,
        NDF=42.0,
        EE=3.0,
        feed_type=FeedComponentType.FORAGE,
    ),
]

ration_config = SimpleNamespace(
    feeds_used=feeds,

    price_list=[1.00, 2.60, 1.05],

    feed_minimum_list=[0.0, 0.0, 5.0],

    feed_maximum_list=[8.0, 5.0, 20.0],

    # Percentuais de extrato etéreo dos ingredientes.
    EE_list=[feed.EE for feed in feeds],

    # Concentrações de FDN dos ingredientes (%).
    NDF_list=[feed.NDF for feed in feeds],

    # Exigência atual de matéria seca.
    animal_requirements=SimpleNamespace(
        dry_matter=20.0,
    ),

    # Exigência inicial de matéria seca.
    initial_dry_matter_requirement=22.0,

    # Tolerância utilizada neste cenário de teste.
    dmi_constraint_fraction=0.30,
)

# Initializes the optimizer.
optimizer = LinearRationOptimizer()

# Solves the model.
result = optimizer.optimize(ration_config)

# Displays the results.
print("Status:", result["status"])
print("Quantities:", result["quantities"])
print("Total cost:", result["cost"])
print(
    "Matéria seca total:",
    sum(result["quantities"].values()),
)

# Converte a solução do HiGHS em um vetor de decisão
# compatível com o otimizador original do RuFaS.
decision_vector = np.array([
    result["quantities"][feed.rufas_id]
    for feed in ration_config.feeds_used
], dtype=float)

# Avalia a solução utilizando as funções originais do RuFaS.
original_cost = RationOptimizer.objective(
    decision_vector,
    ration_config,
)

original_dmi_lower = RationOptimizer.DMI_constraint_lower(
    decision_vector,
    ration_config,
)

original_dmi_upper = RationOptimizer.DMI_constraint_upper(
    decision_vector,
    ration_config,
)

# Exibe os resultados da validação.
print("\n--- VALIDAÇÃO PELO MODELO ORIGINAL ---")

print("Custo original:", original_cost)
print("Restrição DMI inferior:", original_dmi_lower)
print("Restrição DMI superior:", original_dmi_upper)

# Tolerância para diferenças numéricas de ponto flutuante.
tolerance = 1e-6

# Verifica se o solver encontrou uma solução ótima.
assert result["status"] == "Optimal"

# Verifica se o custo esperado foi encontrado.
assert abs(result["cost"] - 14.303333333333333) <= tolerance

# Verifica a equivalência entre as funções objetivo.
assert abs(result["cost"] - original_cost) <= tolerance

# Verifica o atendimento das restrições originais.
assert original_dmi_lower >= -tolerance
assert original_dmi_upper >= -tolerance

print("\nValidação aprovada!")

# Cria uma configuração inviável para testar
# o tratamento de problemas sem solução.
infeasible_config = SimpleNamespace(
    **vars(ration_config)
)

# Altera as exigências sem modificar a configuração original.
infeasible_config.animal_requirements = SimpleNamespace(
    dry_matter=50.0,
)

infeasible_config.initial_dry_matter_requirement = 50.0

# Executa a otimização do problema inviável.
infeasible_result = optimizer.optimize(infeasible_config)

print("\n--- TESTE DE INVIABILIDADE ---")
print(infeasible_result)

# Verifica se a inviabilidade foi identificada.
assert infeasible_result["status"] == "Infeasible"
assert infeasible_result["quantities"] == {}
assert infeasible_result["cost"] is None

print("Teste de inviabilidade aprovado!")

# Validação das restrições de FDN pelo RuFaS original.
original_ndf_lower = RationOptimizer.NDF_constraint_lower(
    decision_vector,
    ration_config,
)

original_ndf_upper = RationOptimizer.NDF_constraint_upper(
    decision_vector,
    ration_config,
)

original_forage_ndf = RationOptimizer.forage_NDF_constraint(
    decision_vector,
    ration_config,
)

print("\n--- VALIDAÇÃO DE FDN ---")

print("FDN mínima:", original_ndf_lower)
print("FDN máxima:", original_ndf_upper)
print("FDN de forragens:", original_forage_ndf)

assert original_ndf_lower >= -tolerance
assert original_ndf_upper >= -tolerance
assert original_forage_ndf >= -tolerance

print("Validação de FDN aprovada!")

# Validação da gordura pelo otimizador original.
original_fat = RationOptimizer.fat_constraint(
    decision_vector,
    ration_config,
)

print("\n--- VALIDAÇÃO DE GORDURA ---")
print("Restrição de gordura:", original_fat)

assert original_fat >= -tolerance

print("Validação de gordura aprovada!")

# Cria um cenário com ingrediente de alto teor de gordura.
high_fat_config = SimpleNamespace(
    **vars(ration_config)
)

# Altera somente o vetor de extrato etéreo do teste.
high_fat_config.EE_list = [12.0, 2.0, 3.0]

# Executa novamente a otimização.
high_fat_result = optimizer.optimize(high_fat_config)

print("\n--- TESTE DE GORDURA ATIVA ---")
print(high_fat_result)

assert high_fat_result["status"] == "Optimal"

# Converte o resultado em vetor de decisão.
high_fat_vector = np.array([
    high_fat_result["quantities"][feed.rufas_id]
    for feed in high_fat_config.feeds_used
], dtype=float)

# Valida a solução pela restrição original.
fat_margin = RationOptimizer.fat_constraint(
    high_fat_vector,
    high_fat_config,
)

print("Folga da restrição de gordura:", fat_margin)

# Verifica se o limite foi respeitado.
assert fat_margin >= -tolerance

# Verifica se a restrição ficou ativa.
assert abs(fat_margin) <= tolerance

print("Teste de gordura ativa aprovado!")