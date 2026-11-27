"""Bounded scientific expression evaluation without Python ``eval``."""

import ast
import math
import operator


class MathEvaluator:
    """Evaluate a small, explicit mathematical grammar over real numbers."""

    MAX_EXPRESSION_LENGTH = 512
    MAX_AST_NODES = 128
    MAX_AST_DEPTH = 32
    MAX_RESULT_MAGNITUDE = 1e100
    MAX_POWER_EXPONENT = 1024
    MAX_FACTORIAL_ARGUMENT = 69
    MAX_ROUND_DIGITS = 12

    CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau}
    OPERATORS = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
        ast.BitXor: operator.pow,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
    }
    FUNCTIONS = {
        "abs": (abs, 1, 1),
        "acos": (math.acos, 1, 1),
        "asin": (math.asin, 1, 1),
        "atan": (math.atan, 1, 1),
        "atan2": (math.atan2, 2, 2),
        "ceil": (math.ceil, 1, 1),
        "cos": (math.cos, 1, 1),
        "cosh": (math.cosh, 1, 1),
        "degrees": (math.degrees, 1, 1),
        "factorial": (math.factorial, 1, 1),
        "floor": (math.floor, 1, 1),
        "hypot": (math.hypot, 2, 2),
        "ln": (math.log, 1, 1),
        "log": (math.log, 1, 2),
        "log10": (math.log10, 1, 1),
        "log2": (math.log2, 1, 1),
        "max": (max, 1, 8),
        "min": (min, 1, 8),
        "radians": (math.radians, 1, 1),
        "round": (round, 1, 2),
        "sin": (math.sin, 1, 1),
        "sinh": (math.sinh, 1, 1),
        "sqrt": (math.sqrt, 1, 1),
        "tan": (math.tan, 1, 1),
        "tanh": (math.tanh, 1, 1),
    }
    FORWARD_TRIGONOMETRY = {"sin", "cos", "tan"}
    INVERSE_TRIGONOMETRY = {"asin", "acos", "atan", "atan2"}

    @classmethod
    def evaluate(cls, expr: str, angle_mode: str = "radians") -> float:
        try:
            if angle_mode not in {"radians", "degrees"}:
                raise ValueError("Angle mode must be radians or degrees")
            if not isinstance(expr, str) or not expr.strip():
                raise ValueError("Expression must be a non-empty string")
            if len(expr) > cls.MAX_EXPRESSION_LENGTH:
                raise ValueError(f"Expression must be at most {cls.MAX_EXPRESSION_LENGTH} characters")
            # Normalize the calculator's conventional power key before parsing so
            # chained powers are right-associative and bind above unary signs.
            tree = ast.parse(expr.replace("^", "**"), mode="eval")
            nodes = [(tree, 1)]
            count = 0
            while nodes:
                node, depth = nodes.pop()
                count += 1
                if count > cls.MAX_AST_NODES:
                    raise ValueError(f"Expression must contain at most {cls.MAX_AST_NODES} syntax nodes")
                if depth > cls.MAX_AST_DEPTH:
                    raise ValueError(f"Expression nesting must not exceed {cls.MAX_AST_DEPTH} levels")
                nodes.extend((child, depth + 1) for child in ast.iter_child_nodes(node))
            return cls._validate_number(cls._eval_node(tree.body, angle_mode))
        except Exception as error:
            raise ValueError(f"Invalid or unsafe mathematical expression: {str(error)}") from error

    @classmethod
    def _validate_number(cls, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Only real numeric results are supported")
        if isinstance(value, int) and value.bit_length() > 1024:
            raise ValueError("Result exceeds the supported numeric range")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Result must be finite")
        if abs(value) > cls.MAX_RESULT_MAGNITUDE:
            raise ValueError("Result exceeds the supported numeric range")
        return value

    @staticmethod
    def _integer_argument(value, label: str) -> int:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{label} must be an integer")
        if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
            raise ValueError(f"{label} must be an integer")
        return int(value)

    @classmethod
    def _eval_node(cls, node, angle_mode: str = "radians"):
        if isinstance(node, ast.Constant):
            return cls._validate_number(node.value)
        if isinstance(node, ast.Name):
            if node.id not in cls.CONSTANTS:
                raise ValueError(f"Unknown mathematical constant: {node.id}")
            return cls.CONSTANTS[node.id]
        if isinstance(node, ast.BinOp):
            left = cls._eval_node(node.left, angle_mode)
            right = cls._eval_node(node.right, angle_mode)
            op_type = type(node.op)
            if op_type not in cls.OPERATORS:
                raise ValueError(f"Unsupported operator: {op_type}")
            if op_type in (ast.Pow, ast.BitXor):
                if abs(right) > cls.MAX_POWER_EXPONENT:
                    raise ValueError(f"Exponent magnitude must not exceed {cls.MAX_POWER_EXPONENT}")
                if right > 0 and abs(left) > 1:
                    estimated_bits = math.log2(abs(left)) * right
                    if estimated_bits > math.log2(cls.MAX_RESULT_MAGNITUDE):
                        raise ValueError("Result exceeds the supported numeric range")
                if right < 0 and 0 < abs(left) < 1:
                    estimated_bits = math.log2(1 / abs(left)) * abs(right)
                    if estimated_bits > math.log2(cls.MAX_RESULT_MAGNITUDE):
                        raise ValueError("Result exceeds the supported numeric range")
            return cls._validate_number(cls.OPERATORS[op_type](left, right))
        if isinstance(node, ast.UnaryOp):
            operand = cls._eval_node(node.operand, angle_mode)
            op_type = type(node.op)
            if op_type not in cls.OPERATORS:
                raise ValueError(f"Unsupported unary operator: {op_type}")
            return cls._validate_number(cls.OPERATORS[op_type](operand))
        if isinstance(node, ast.Call):
            return cls._eval_call(node, angle_mode)
        raise ValueError(f"Disallowed syntax node: {type(node)}")

    @classmethod
    def _eval_call(cls, node: ast.Call, angle_mode: str):
        if not isinstance(node.func, ast.Name) or node.keywords:
            raise ValueError("Only direct calls to supported functions are allowed")
        name = node.func.id
        if name not in cls.FUNCTIONS:
            raise ValueError(f"Unsupported mathematical function: {name}")
        function, minimum, maximum = cls.FUNCTIONS[name]
        if not minimum <= len(node.args) <= maximum:
            raise ValueError(f"{name} accepts between {minimum} and {maximum} arguments")
        arguments = [cls._eval_node(argument, angle_mode) for argument in node.args]

        if name == "factorial":
            value = cls._integer_argument(arguments[0], "factorial argument")
            if not 0 <= value <= cls.MAX_FACTORIAL_ARGUMENT:
                raise ValueError(f"factorial argument must be from 0 to {cls.MAX_FACTORIAL_ARGUMENT}")
            arguments[0] = value
        if name == "round" and len(arguments) == 2:
            digits = cls._integer_argument(arguments[1], "round digits")
            if abs(digits) > cls.MAX_ROUND_DIGITS:
                raise ValueError(f"round digits must be between {-cls.MAX_ROUND_DIGITS} and {cls.MAX_ROUND_DIGITS}")
            arguments[1] = digits

        if name in cls.FORWARD_TRIGONOMETRY and angle_mode == "degrees":
            arguments[0] = math.radians(arguments[0])
        result = function(*arguments)
        if name in cls.INVERSE_TRIGONOMETRY and angle_mode == "degrees":
            result = math.degrees(result)
        return cls._validate_number(result)
