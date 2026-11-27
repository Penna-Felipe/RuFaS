from types import SimpleNamespace
import numpy as np

from RUFAS.biophysical.animal.ration.otimizador_alimentar_linear import (
    LinearRationOptimizer,
)

from RUFAS.biophysical.animal.ration.ration_optimizer import (
    RationOptimizer,
)

# Simulated feed identifiers.
feeds = [
    SimpleNamespace(rufas_id=18),
    SimpleNamespace(rufas_id=44),
    SimpleNamespace(rufas_id=50),
]

# Simulated ration configuration.
ration_config = SimpleNamespace(
    feeds_used=feeds,
    price_list=[1.00, 2.60, 1.05],
    feed_minimum_list=[0.0, 0.0, 5.0],
    feed_maximum_list=[8.0, 5.0, 20.0],

    # Exigências utilizadas nas restrições de DMI.
    animal_requirements=SimpleNamespace(
        dry_matter=20.0,
    ),

    initial_dry_matter_requirement=22.0,

    # Tolerância de 30% utilizada neste teste.
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
assert abs(result["cost"] - 14.30) <= tolerance

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