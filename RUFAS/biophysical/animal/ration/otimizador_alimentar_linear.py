"""
Otimizador linear para formulação de dietas de menor custo.

Utiliza PuLP para a modelagem matemática e HiGHS para
a resolução do problema de programação linear.
"""

import pulp

from RUFAS.biophysical.animal.ration.ration_optimizer import (
    RationConfig,
)


class LinearRationOptimizer:
    """
    Otimizador linear de dietas alimentares.

    Reaproveita as exigências nutricionais, os preços,
    as propriedades dos alimentos e os limites de
    inclusão fornecidos pelo RuFaS.
    """

    def __init__(self) -> None:
        """
        Inicializa o otimizador linear.
        """

        # Inicializa o solver HiGHS.
        # msg=False desabilita os logs do solver.
        self.solver = pulp.HiGHS(msg=False)

    @staticmethod
    def _build_model(
        ration_config: RationConfig,
    ) -> tuple[pulp.LpProblem, list[pulp.LpVariable]]:
        """
        Constrói o modelo matemático de menor custo.

        Parâmetros
        ----------
        ration_config : RationConfig
            Objeto que contém as exigências nutricionais,
            os alimentos disponíveis, os preços e os
            limites de inclusão.

        Retorno
        -------
        tuple
            Modelo matemático e lista de variáveis
            de decisão.
        """

        # Cria um problema de minimização.
        model = pulp.LpProblem(
            "Linear_Ration_Optimization",
            pulp.LpMinimize,
        )

        # VARIÁVEIS DE DECISÃO
        #
        # Cada variável x_i representa a quantidade de
        # matéria seca do ingrediente i, em kg/animal/dia.
        #
        # Referência no código original:
        # ration_optimizer.py -> RationConfig.__init__()
        # ration_optimizer.py -> RationOptimizer._build_bounds()
        #
        # Representação matemática:
        # limite_min_i <= x_i <= limite_max_i

        variables = [
            pulp.LpVariable(
                name=f"feed_{feed.rufas_id}",
                lowBound=ration_config.feed_minimum_list[i],
                upBound=ration_config.feed_maximum_list[i],
                cat=pulp.LpContinuous,
            )
            for i, feed in enumerate(ration_config.feeds_used)
        ]

        # FUNÇÃO OBJETIVO
        #
        # Minimiza o custo total dos ingredientes.
        #
        # Referência no código original:
        # ration_optimizer.py -> RationOptimizer.objective()
        #
        # Representação matemática:
        # Minimizar Z = somatório(c_i * x_i)
        #
        # c_i: preço do ingrediente i.
        # x_i: quantidade do ingrediente i.
        #
        # A função objetivo original já é linear.
        # Portanto, não necessita de aproximações.

        model += pulp.lpSum(
            ration_config.price_list[i] * variables[i]
            for i in range(len(variables))
        ), "Total_Feed_Cost"

        # Retorna o modelo e suas variáveis de decisão.
        return model, variables

    @staticmethod
    def _add_dmi_constraints(
        model: pulp.LpProblem,
        variables: list[pulp.LpVariable],
        ration_config: RationConfig,
    ) -> None:
        """
        Adiciona as restrições de consumo de matéria seca.

        Preserva as restrições inferior e superior
        utilizadas pelo otimizador original do RuFaS.

        Parâmetros
        ----------
        model : pulp.LpProblem
            Modelo matemático de programação linear.
        variables : list[pulp.LpVariable]
            Variáveis de decisão dos ingredientes,
            expressas em kg de MS por animal por dia.
        ration_config : RationConfig
            Exigências nutricionais e parâmetros
            utilizados na formulação da dieta.
        """

        # Matéria seca total fornecida pela dieta.
        # Representação matemática: somatório(x_i).
        total_dmi = pulp.lpSum(variables)

        # Exigência atual de matéria seca.
        current_dmi = ration_config.animal_requirements.dry_matter

        # Exigência inicial de matéria seca.
        initial_dmi = ration_config.initial_dry_matter_requirement

        # Fração de tolerância permitida pelo RuFaS.
        tolerance = ration_config.dmi_constraint_fraction

        # RESTRIÇÃO INFERIOR DE MATÉRIA SECA
        #
        # Referência no código original:
        # ration_optimizer.py ->
        # RationOptimizer.DMI_constraint_lower()
        #
        # Equação:
        # somatório(x_i) >= D * (1 - alpha)

        minimum_dmi = current_dmi * (1 - tolerance)

        model += (
            total_dmi >= minimum_dmi,
            "DMI_Minimum",
        )

        # RESTRIÇÃO SUPERIOR DE MATÉRIA SECA
        #
        # Referência no código original:
        # ration_optimizer.py ->
        # RationOptimizer.DMI_constraint_upper()
        #
        # Equação:
        # somatório(x_i) <= D0 * (1 + alpha)

        maximum_dmi = initial_dmi * (1 + tolerance)

        model += (
            total_dmi <= maximum_dmi,
            "DMI_Maximum",
        )

    def optimize(
        self,
        ration_config: RationConfig,
    ) -> dict:
        """
        Resolve o problema de programação linear.

        Parâmetros
        ----------
        ration_config : RationConfig
            Informações necessárias para a formulação
            da dieta.

        Retorno
        -------
        dict
            Status da otimização, quantidades dos
            ingredientes e custo total.
        """

        # Constrói o modelo matemático.
        model, variables = self._build_model(ration_config)

        # Adiciona as restrições de matéria seca.
        self._add_dmi_constraints(
            model,
            variables,
            ration_config,
        )

        # Executa a otimização utilizando HiGHS.
        status = model.solve(self.solver)

        # Verifica se uma solução ótima foi encontrada.
        if status != pulp.LpStatusOptimal:
            return {
                "status": pulp.LpStatus[status],
                "quantities": {},
                "cost": None,
            }

        # Recupera os valores ótimos das variáveis.
        #
        # A estrutura de IDs e quantidades segue a ideia
        # do método original:
        # ration_optimizer.py ->
        # RationOptimizer.make_ration_from_solution()
        #
        # Nesta etapa não realizamos arredondamentos.

        quantities = {
            feed.rufas_id: variables[i].varValue
            for i, feed in enumerate(ration_config.feeds_used)
        }

        # Recupera o valor da função objetivo.
        total_cost = pulp.value(model.objective)

        # Retorna os resultados da otimização.
        return {
            "status": pulp.LpStatus[status],
            "quantities": quantities,
            "cost": total_cost,
        }