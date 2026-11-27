"""
Otimizador linear para formulação de dietas de menor custo.

Utiliza PuLP para a modelagem matemática e HiGHS para
a resolução do problema de programação linear.
"""

import pulp

from RUFAS.biophysical.animal.ration.ration_optimizer import (
    RationConfig,
)

from RUFAS.biophysical.animal.animal_module_constants import (
    AnimalModuleConstants,
)

from RUFAS.data_structures.feed_storage_to_animal_connection import (
    FeedComponentType,
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

    @staticmethod
    def _add_ndf_constraints(
        model: pulp.LpProblem,
        variables: list[pulp.LpVariable],
        ration_config: RationConfig,
    ) -> None:
        """
        Adiciona as restrições de FDN mínima e máxima.

        As restrições fracionárias do otimizador original
        são reformuladas algebricamente para programação
        linear, considerando matéria seca total positiva.
        """

        # Quantidade total de matéria seca.
        # Representação: somatório(x_i).
        total_dmi = pulp.lpSum(variables)

        # Soma ponderada das concentrações de FDN.
        #
        # Os valores de NDF_list estão em percentual.
        # Representação: somatório(f_i * x_i).
        #
        # Dividir esta expressão por 100 forneceria
        # a quantidade de FDN em kg.
        weighted_ndf = pulp.lpSum(
            ration_config.NDF_list[i] * variables[i]
            for i in range(len(variables))
        )

        # Limites nutricionais definidos pelo RuFaS.
        minimum_ndf = AnimalModuleConstants.MINIMUM_RATION_NDF
        maximum_ndf = AnimalModuleConstants.MAXIMUM_RATION_NDF

        # RESTRIÇÃO DE FDN MÍNIMA
        #
        # Origem:
        # ration_optimizer.py ->
        # RationOptimizer.NDF_constraint_lower()
        #
        # Equação original:
        # somatório(f_i * x_i) / somatório(x_i) >= F_min
        #
        # Reformulação linear exata para DMI > 0:
        # somatório(f_i * x_i) >= F_min * somatório(x_i)

        model += (
            weighted_ndf >= minimum_ndf * total_dmi,
            "NDF_Minimum",
        )

        # RESTRIÇÃO DE FDN MÁXIMA
        #
        # Origem:
        # ration_optimizer.py ->
        # RationOptimizer.NDF_constraint_upper()
        #
        # Equação original:
        # somatório(f_i * x_i) / somatório(x_i) <= F_max
        #
        # Reformulação linear exata para DMI > 0:
        # somatório(f_i * x_i) <= F_max * somatório(x_i)

        model += (
            weighted_ndf <= maximum_ndf * total_dmi,
            "NDF_Maximum",
        )

    @staticmethod
    def _add_forage_ndf_constraint(
        model: pulp.LpProblem,
        variables: list[pulp.LpVariable],
        ration_config: RationConfig,
    ) -> None:
        """
        Adiciona a restrição mínima de FDN proveniente
        de forragens na dieta.

        A reformulação linear preserva a restrição
        original para dietas com matéria seca positiva.
        """

        # Matéria seca total fornecida pela dieta.
        # Representação: somatório(x_i).
        total_dmi = pulp.lpSum(variables)

        # Soma ponderada da FDN proveniente de forragens.
        #
        # Origem no código original:
        # nutrition_supply_calculator.py ->
        # NutritionSupplyCalculator.
        # calculate_forage_neutral_detergent_fiber_content()
        #
        # Considera exclusivamente os ingredientes
        # classificados como FeedComponentType.FORAGE.
        #
        # Os valores de NDF estão em escala percentual.

        forage_ndf = pulp.lpSum(
            feed.NDF * variables[i]
            for i, feed in enumerate(ration_config.feeds_used)
            if feed.feed_type == FeedComponentType.FORAGE
        )

        # Limite mínimo estabelecido pelo RuFaS.
        minimum_forage_ndf = (
            AnimalModuleConstants.MINIMUM_RATION_FORAGE_NDF
        )

        # RESTRIÇÃO DE FDN DE FORRAGENS
        #
        # Origem no código original:
        # ration_optimizer.py ->
        # RationOptimizer.forage_NDF_constraint()
        #
        # Equação original:
        # somatório(f_i * v_i * x_i) / somatório(x_i) >= F_min
        #
        # Reformulação linear exata para DMI > 0:
        # somatório(f_i * v_i * x_i) >= F_min * somatório(x_i)

        model += (
            forage_ndf >= minimum_forage_ndf * total_dmi,
            "Forage_NDF_Minimum",
        )

    @staticmethod
    def _add_fat_constraint(
        model: pulp.LpProblem,
        variables: list[pulp.LpVariable],
        ration_config: RationConfig,
    ) -> None:
        """
        Adiciona a restrição de gordura máxima da dieta.

        A reformulação linear é equivalente à restrição
        original para dietas com matéria seca positiva.
        """

        # Quantidade total de matéria seca da dieta.
        # Representação: somatório(x_i).
        total_dmi = pulp.lpSum(variables)

        # Soma ponderada dos percentuais de extrato etéreo.
        # Representação: somatório(e_i * x_i).
        #
        # Os valores de EE_list estão em escala percentual.
        weighted_fat = pulp.lpSum(
            ration_config.EE_list[i] * variables[i]
            for i in range(len(variables))
        )

        # Limite máximo de gordura estabelecido pelo RuFaS.
        #
        # Origem:
        # animal_module_constants.py ->
        # AnimalModuleConstants.MAXIMUM_RATION_FAT
        maximum_fat = AnimalModuleConstants.MAXIMUM_RATION_FAT

        # RESTRIÇÃO DE GORDURA MÁXIMA
        #
        # Origem no código original:
        # ration_optimizer.py ->
        # RationOptimizer.fat_constraint()
        #
        # Equação original:
        # E_max - somatório(e_i * x_i) / somatório(x_i) >= 0
        #
        # Reformulação linear exata para DMI > 0:
        # somatório(e_i * x_i) <= E_max * somatório(x_i)

        model += (
            weighted_fat <= maximum_fat * total_dmi,
            "Fat_Maximum",
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

        # Restrições de matéria seca.
        self._add_dmi_constraints(
            model, variables, ration_config
        )

        # Restrições de FDN mínima e máxima.
        self._add_ndf_constraints(
            model, variables, ration_config
        )

        # Restrição de FDN proveniente de forragens.
        self._add_forage_ndf_constraint(
            model, variables, ration_config
        )

        # Restrição de gordura máxima.
        self._add_fat_constraint(
            model, variables, ration_config
        )

        # Executa o HiGHS.
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