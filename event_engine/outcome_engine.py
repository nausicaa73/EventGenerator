
import random
import sqlite3


# ============================================================
# Registres extensibles
# ============================================================

CONDITION_HANDLERS = {}
REWARD_HANDLERS = {}


def register_condition(condition_type):
    """Enregistre un type de condition."""
    def decorator(function):
        CONDITION_HANDLERS[condition_type] = function
        return function
    return decorator


def register_reward(reward_type):
    """Enregistre un type de récompense."""
    def decorator(function):
        REWARD_HANDLERS[reward_type] = function
        return function
    return decorator


# ============================================================
# Conditions
# ============================================================

@register_condition("balance")
def condition_balance(condition, context):
    resource = condition.get("currency", "currency")
    operator = condition.get("operator", "gt")
    expected = condition.get("value")

    if resource not in ("currency", "points"):
        raise ValueError(f"Ressource inconnue : {resource}")

    if type(expected) not in (int, float):
        raise ValueError("La valeur d'une condition doit être numérique.")

    actual = context["balances"].get(resource, 0)

    operators = {
        "eq": lambda a, b: a == b,
        "ne": lambda a, b: a != b,
        "gt": lambda a, b: a > b,
        "gte": lambda a, b: a >= b,
        "lt": lambda a, b: a < b,
        "lte": lambda a, b: a <= b,
    }

    if operator not in operators:
        raise ValueError(f"Opérateur de condition inconnu : {operator}")

    return operators[operator](actual, expected)


def evaluate_condition(condition, context):
    """Évalue une condition ou une combinaison de conditions."""
    condition_type = condition.get("type")

    if condition_type == "all":
        children = condition.get("conditions", [])
        return all(evaluate_condition(item, context) for item in children)

    if condition_type == "any":
        children = condition.get("conditions", [])
        return any(evaluate_condition(item, context) for item in children)

    if condition_type == "not":
        child = condition.get("condition")
        if not isinstance(child, dict):
            raise ValueError("La condition 'not' nécessite une condition.")
        return not evaluate_condition(child, context)

    handler = CONDITION_HANDLERS.get(condition_type)

    if handler is None:
        raise ValueError(f"Type de condition inconnu : {condition_type}")

    return bool(handler(condition, context))


# ============================================================
# Tirages aléatoires
# ============================================================

def choose_value(specification):
    """
    Tire une valeur dans une liste.

    Sans weights : chaque valeur a la même probabilité.
    Avec weights : chaque poids correspond à la valeur de même index.
    """
    values = specification.get("values")

    if not isinstance(values, list) or not values:
        raise ValueError("Une récompense doit contenir une liste values.")

    if not all(type(value) in (int, float) for value in values):
        raise ValueError("Les valeurs des récompenses doivent être numériques.")

    weights = specification.get("weights")

    if weights is None:
        return random.choice(values)

    if (
        not isinstance(weights, list)
        or len(weights) != len(values)
        or not all(
            isinstance(weight, (int, float))
            and weight >= 0
            for weight in weights
        )
        or sum(weights) <= 0
    ):
        raise ValueError(
            "Les poids doivent être positifs ou nuls, "
            "correspondre aux valeurs et avoir une somme positive."
        )

    return random.choices(values, weights=weights, k=1)[0]


def choose_outcome(outcomes):
    """Sélectionne une issue en fonction de ses probabilités."""
    if not isinstance(outcomes, list) or not outcomes:
        raise ValueError("Aucune issue n'est configurée.")

    weights = []

    for outcome in outcomes:
        probability = outcome.get("probability")

        if (
            not isinstance(probability, (int, float))
            or isinstance(probability, bool)
            or probability < 0
        ):
            raise ValueError(
                f"Probabilité invalide pour l'issue {outcome.get('id')}."
            )

        weights.append(probability)

    if sum(weights) <= 0:
        raise ValueError("La somme des probabilités doit être positive.")

    return random.choices(outcomes, weights=weights, k=1)[0]


# ============================================================
# Récompenses
# ============================================================

@register_reward("currency")
def reward_currency(connection, user_id, specification, context):
    value = choose_value(specification)

    # Empêche de perdre davantage de monnaie que le joueur n'en possède.
    current = context["balances"].get("currency", 0)

    if value < 0 and specification.get("limit_to_balance", True):
        value = max(value, -current)

    connection.execute(
        """
        UPDATE players
        SET currency = currency + ?
        WHERE user_id = ?
        """,
        (value, user_id),
    )

    context["balances"]["currency"] = current + value
    return value


@register_reward("points")
def reward_points(connection, user_id, specification, context):
    value = choose_value(specification)
    current = context["balances"].get("points", 0)

    if value < 0 and specification.get("limit_to_balance", True):
        value = max(value, -current)

    connection.execute(
        """
        UPDATE players
        SET points = points + ?
        WHERE user_id = ?
        """,
        (value, user_id),
    )

    context["balances"]["points"] = current + value
    return value


# ============================================================
# Exécution d'une activité à issues multiples
# ============================================================

def select_branch(outcome, context):
    """Retourne la première branche dont toutes les conditions passent."""
    branches = outcome.get("branches")

    if branches is None:
        return outcome

    for branch in branches:
        conditions = branch.get("conditions", [])

        if all(
            evaluate_condition(condition, context)
            for condition in conditions
        ):
            return branch

    raise ValueError(
        f"Aucune branche ne correspond à l'issue {outcome.get('id')}."
    )


def execute_outcome(connection, user_id, activity, player):
    """
    Tire l'issue, vérifie ses conditions et applique les récompenses.

    À appeler à l'intérieur d'une transaction SQLite.
    """
    outcome = choose_outcome(activity.get("outcomes", []))

    context = {
        "user_id": user_id,
        "balances": {
            "currency": player["currency"],
            "points": player["points"],
        },
    }

    branch = select_branch(outcome, context)
    rewards = {}

    for specification in branch.get("rewards", []):
        reward_type = specification.get("type")
        handler = REWARD_HANDLERS.get(reward_type)

        if handler is None:
            raise ValueError(f"Type de récompense inconnu : {reward_type}")

        delta = handler(connection, user_id, specification, context)
        rewards[reward_type] = rewards.get(reward_type, 0) + delta

    # Montants affichables : positifs, même en cas de perte.
    template_values = {
        "amount": abs(rewards.get("currency", 0)),
        "currency_amount": abs(rewards.get("currency", 0)),
        "currency_delta": rewards.get("currency", 0),
        "points_amount": abs(rewards.get("points", 0)),
        "points_delta": rewards.get("points", 0),
        "balance": context["balances"]["currency"],
        "points_balance": context["balances"]["points"],
    }

    messages = branch.get("messages", [])
    message = random.choice(messages) if messages else ""

    try:
        message = message.format_map(template_values)
    except (KeyError, ValueError) as error:
        raise ValueError(
            f"Variable de message inconnue ou invalide : {error}"
        ) from error

    images = branch.get("images", [])
    image = random.choice(images) if images else None

    return {
        "status": "success",
        "outcome": outcome.get("id"),
        "rewards": rewards,
        "balances": context["balances"],
        "message": message,
        "image": image,
    }
