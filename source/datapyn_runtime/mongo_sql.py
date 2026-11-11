"""A deliberately small SQL SELECT compiler; all data work stays on MongoDB.

This is not MongoSQL/SQL-92. Unsupported syntax fails before any network I/O.
The three-valued predicate compiler keeps NOT/IN and missing fields SQL-safe.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import math

MAX_QUERY_BYTES = 128 * 1024
MAX_AST_NODES = 10_000
MAX_AST_DEPTH = 60
MAX_PARAMETERS = 1000
_NUMERIC_TYPES = ["int", "long", "double", "decimal"]
_SCALAR_TYPES = _NUMERIC_TYPES + ["string", "bool", "date", "objectId", "binData"]


class UnsupportedMongoSql(ValueError):
    code = "unsupported_query"


@dataclass(frozen=True)
class MongoQuery:
    database: str
    collection: str
    pipeline: list[dict]
    columns: list[str] | None
    limit_zero: bool = False


def _unsupported(detail):
    raise UnsupportedMongoSql(f"SQL MongoDB: {detail}. Use SELECT, campos, WHERE, ORDER BY e LIMIT/OFFSET.")


def _only_args(node, allowed):
    for key, value in node.args.items():
        if key not in allowed and value is not None and value is not False and value != []:
            _unsupported(f"{key.upper()} não é suportado nesta versão")


def _identifier(node, *, output=False):
    from sqlglot import exp

    if not isinstance(node, exp.Identifier):
        _unsupported("identificador inválido")
    name = node.name
    if not name or "\x00" in name or name.startswith("$") or output and "." in name:
        _unsupported("identificador com caractere não suportado")
    return name


def _bson_scalar(value):
    """No operator, JS, regex object or implicit lossy numeric coercion."""
    if value is None or isinstance(value, (str, bool, datetime, bytes)):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if isinstance(value, int):
        if -(2**63) <= value < 2**63:
            return value
        value = Decimal(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            _unsupported("parâmetro numérico não finito")
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            _unsupported("parâmetro decimal não finito")
        from bson.decimal128 import Decimal128
        try:
            return Decimal128(value)
        except (ArithmeticError, ValueError) as error:
            raise UnsupportedMongoSql("SQL MongoDB: valor fora da precisão Decimal128.") from error
    if type(value).__module__.startswith("bson.") and type(value).__name__ in {"ObjectId", "Decimal128", "Binary", "Int64"}:
        return value
    _unsupported("tipo de parâmetro não escalar ou não suportado")


class _Compiler:
    def __init__(self, table, parameters):
        self.table = table
        self.alias = table.alias
        self.parameters = parameters

    def column(self, node):
        from sqlglot import exp

        if not isinstance(node, exp.Column) or isinstance(node.this, exp.Star):
            _unsupported("expressão de campo não suportada")
        _only_args(node, {"this", "table", "db", "catalog"})
        parts = [_identifier(part) for part in node.parts]
        qualifiers = [self.alias] if self.alias else [self.table.name]
        if self.table.db:
            qualifiers.append(self.table.db + "." + self.table.name)
        path = ".".join(parts)
        for qualifier in sorted((q for q in qualifiers if q), key=len, reverse=True):
            if path.startswith(qualifier + "."):
                parts = path[len(qualifier) + 1:].split(".")
                break
        # Quoted dotted names are literal BSON keys, not a nested path. They
        # would need $getField, which is not portable to Cosmos Mongo.
        if any("." in part.name for part in node.parts):
            _unsupported("campo literal com ponto; use partes separadas para campos aninhados")
        if not parts:
            _unsupported("campo vazio")
        return ".".join(parts)

    def value(self, node):
        from sqlglot import exp

        if isinstance(node, exp.Paren):
            return self.value(node.this)
        if isinstance(node, exp.Column):
            return "$" + self.column(node)
        if isinstance(node, exp.Null):
            value = None
        elif isinstance(node, exp.Boolean):
            value = node.this
        elif isinstance(node, exp.Literal):
            if node.is_string:
                value = node.this
            else:
                try:
                    value = Decimal(node.this) if any(char in node.this.lower() for char in ".e") else int(node.this)
                except (InvalidOperation, ValueError):
                    _unsupported("literal numérico inválido")
        elif isinstance(node, exp.Neg) and isinstance(node.this, exp.Literal) and not node.this.is_string:
            value = -Decimal(node.this.this)
            if value == value.to_integral_value():
                value = int(value)
        elif isinstance(node, (exp.Placeholder, exp.Parameter)):
            name = node.name
            if not name or name not in self.parameters:
                raise UnsupportedMongoSql(f"SQL MongoDB: informe o parâmetro {name or 'nomeado'}.")
            value = self.parameters[name]
        else:
            _unsupported(f"expressão {type(node).__name__} não suportada")
        return {"$literal": _bson_scalar(value)}

    @staticmethod
    def _nonnull(value):
        return {"$ne": [{"$ifNull": [value, None]}, None]}

    def comparison(self, left, right, operator, inverse):
        left, right = self.value(left), self.value(right)
        left_type, right_type = {"$type": left}, {"$type": right}
        # MongoDB's BSON order compares unrelated types (e.g. strings > ints).
        # SQL scalar predicates must not accidentally match those documents.
        comparable = {"$or": [
            {"$and": [{"$in": [left_type, _NUMERIC_TYPES]}, {"$in": [right_type, _NUMERIC_TYPES]}]},
            {"$and": [{"$eq": [left_type, right_type]}, {"$in": [left_type, _SCALAR_TYPES]}]},
        ]}
        guard = [self._nonnull(left), self._nonnull(right), comparable]
        return ({"$and": [*guard, {operator: [left, right]}]},
                {"$and": [*guard, {inverse: [left, right]}]})

    def index_filter(self, node):
        """An optional necessary filter gives indexed fields a sargable match.

        The full $expr still checks scalar types/NULL semantics; this filter
        must only narrow candidates, never replace the SQL truth predicate.
        """
        from sqlglot import exp

        if isinstance(node, exp.Paren):
            return self.index_filter(node.this)
        if isinstance(node, (exp.And, exp.Or)):
            left, right = self.index_filter(node.this), self.index_filter(node.expression)
            if isinstance(node, exp.Or):
                return {"$or": [left, right]} if left and right else None
            filters = [item for item in (left, right) if item]
            return {"$and": filters} if filters else None
        operators = {exp.EQ: "$eq", exp.NEQ: "$ne", exp.GT: "$gt", exp.GTE: "$gte", exp.LT: "$lt", exp.LTE: "$lte"}
        if type(node) in operators and isinstance(node.this, exp.Column) and not isinstance(node.expression, exp.Column):
            value = self.value(node.expression)
            if "$literal" in value and value["$literal"] is not None:
                return {self.column(node.this): {operators[type(node)]: value["$literal"]}}
        return None

    def predicate(self, node):
        from sqlglot import exp

        if isinstance(node, exp.Paren):
            return self.predicate(node.this)
        if isinstance(node, exp.Not):
            yes, no = self.predicate(node.this)
            return no, yes
        if isinstance(node, (exp.And, exp.Or)):
            left, right = self.predicate(node.this), self.predicate(node.expression)
            yes_op, no_op = ("$and", "$or") if isinstance(node, exp.And) else ("$or", "$and")
            return {yes_op: [left[0], right[0]]}, {no_op: [left[1], right[1]]}
        operators = {exp.EQ: ("$eq", "$ne"), exp.NEQ: ("$ne", "$eq"), exp.GT: ("$gt", "$lte"),
                     exp.GTE: ("$gte", "$lt"), exp.LT: ("$lt", "$gte"), exp.LTE: ("$lte", "$gt")}
        if type(node) in operators:
            return self.comparison(node.this, node.expression, *operators[type(node)])
        if isinstance(node, exp.Is):
            if not isinstance(node.expression, (exp.Null, exp.Boolean)):
                _unsupported("IS aceita apenas NULL, TRUE ou FALSE")
            left = {"$ifNull": [self.value(node.this), None]}
            right = self.value(node.expression)
            return {"$eq": [left, right]}, {"$ne": [left, right]}
        if isinstance(node, exp.In):
            _only_args(node, {"this", "expressions"})
            if not node.expressions or len(node.expressions) > MAX_PARAMETERS:
                _unsupported("IN requer uma lista limitada de valores escalares")
            if any(isinstance(item, exp.Column) for item in node.expressions):
                _unsupported("IN requer valores ou parâmetros")
            pairs = [self.comparison(node.this, item, "$eq", "$ne") for item in node.expressions]
            return {"$or": [pair[0] for pair in pairs]}, {"$and": [pair[1] for pair in pairs]}
        if isinstance(node, exp.Null):
            return {"$literal": False}, {"$literal": False}
        if isinstance(node, (exp.Boolean, exp.Column)):
            return (
                {"$eq": [{"$ifNull": [self.value(node), None]}, True]},
                {"$eq": [{"$ifNull": [self.value(node), None]}, False]})
        _unsupported(f"filtro {type(node).__name__} não suportado")

    def page_integer(self, node, name):
        from sqlglot import exp

        _only_args(node, {"expression"})
        expression = node.expression
        if isinstance(expression, (exp.Placeholder, exp.Parameter)):
            value = self.value(expression)["$literal"]
        elif isinstance(expression, exp.Literal) and not expression.is_string:
            try:
                value = int(expression.this)
            except ValueError:
                _unsupported(f"{name} requer inteiro não negativo")
        else:
            _unsupported(f"{name} requer inteiro não negativo")
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 2**63:
            _unsupported(f"{name} requer inteiro não negativo de 64 bits")
        return value


def compile_query(query, parameters=None, database=""):
    """Compile one supported SELECT, without a client, credentials or I/O."""
    from sqlglot import exp, parse
    from sqlglot.errors import SqlglotError

    if not isinstance(query, str) or not query.strip() or len(query.encode("utf-8")) > MAX_QUERY_BYTES:
        _unsupported("consulta vazia ou maior que 128 KiB")
    if isinstance(parameters, list):
        from src.utils.sql_parameter_service import prepare_generic_sql
        prepared = prepare_generic_sql(query, parameters)
        query, parameters = prepared.query, prepared.params
    if parameters is not None and not isinstance(parameters, dict):
        _unsupported("parâmetros devem ser nomeados")
    if len(parameters or {}) > MAX_PARAMETERS:
        _unsupported("parâmetros demais")
    try:
        expressions = [item for item in parse(query) if item is not None]
    except (SqlglotError, RecursionError) as error:
        raise UnsupportedMongoSql("SQL MongoDB: sintaxe inválida ou complexa demais.") from error
    if len(expressions) != 1 or not isinstance(expressions[0], exp.Select):
        _unsupported("somente um SELECT é permitido por execução")
    select = expressions[0]
    nodes = list(select.walk())
    if len(nodes) > MAX_AST_NODES or any(node.depth > MAX_AST_DEPTH for node in nodes):
        _unsupported("consulta complexa demais")
    _only_args(select, {"expressions", "from_", "where", "order", "limit", "offset"})
    source = select.args.get("from_")
    if not isinstance(source, exp.From) or not isinstance(source.this, exp.Table):
        _unsupported("informe uma collection no FROM")
    _only_args(source, {"this"})
    table = source.this
    _only_args(table, {"this", "db", "alias"})
    collection = _identifier(table.this)
    selected_database = _identifier(table.args["db"]) if table.args.get("db") else database
    if table.args.get("alias"):
        _only_args(table.args["alias"], {"this"})
        _identifier(table.args["alias"].this)
    compiler = _Compiler(table, parameters or {})
    pipeline = []
    where = select.args.get("where")
    if where is not None:
        _only_args(where, {"this"})
        truth = compiler.predicate(where.this)[0]
        candidates = compiler.index_filter(where.this)
        if candidates:
            pipeline.append({"$match": candidates})
        pipeline.append({"$match": {"$expr": truth}})

    columns, projection, aliases = [], {}, {}
    if len(select.expressions) == 1 and (isinstance(select.expressions[0], exp.Star) or
            isinstance(select.expressions[0], exp.Column) and isinstance(select.expressions[0].this, exp.Star)):
        star = select.expressions[0]
        if isinstance(star, exp.Column) and star.table not in {table.alias_or_name}:
            _unsupported("qualificador do asterisco inválido")
        _only_args(star.this if isinstance(star, exp.Column) else star, set())
        columns = None
    else:
        for expression in select.expressions:
            node = expression.this if isinstance(expression, exp.Alias) else expression
            if isinstance(expression, exp.Alias):
                _only_args(expression, {"this", "alias"})
                name = _identifier(expression.args["alias"], output=True)
            elif isinstance(node, exp.Column) and not isinstance(node.this, exp.Star):
                name = _identifier(node.this, output=True)
            else:
                _unsupported("projeção requer campo ou literal com alias")
            if name in projection:
                _unsupported("campos de saída duplicados; informe aliases distintos")
            projection[name] = {"$ifNull": [compiler.value(node), None]}
            columns.append(name)
            if isinstance(node, exp.Column):
                aliases[name] = compiler.column(node)
        if not projection:
            _unsupported("SELECT requer pelo menos um campo")

    order = select.args.get("order")
    if order is not None:
        _only_args(order, {"expressions"})
        sorting = {}
        for ordered in order.expressions:
            if not isinstance(ordered, exp.Ordered):
                _unsupported("ORDER BY requer campos")
            _only_args(ordered, {"this", "desc", "nulls_first"})
            descending = bool(ordered.args.get("desc"))
            if ordered.args.get("nulls_first") is not (not descending):
                _unsupported("ordenação NULLS FIRST/LAST diferente da ordem BSON")
            field = compiler.column(ordered.this)
            if isinstance(ordered.this, exp.Column) and not ordered.this.table:
                if field in projection and field not in aliases:
                    _unsupported("ORDER BY de alias literal não é suportado")
                field = aliases.get(field, field)
            if field in sorting:
                _unsupported("ORDER BY contém campo repetido")
            sorting[field] = -1 if descending else 1
        if not sorting or len(sorting) > 32:
            _unsupported("ORDER BY requer de 1 a 32 campos")
        pipeline.append({"$sort": sorting})
    offset = compiler.page_integer(select.args["offset"], "OFFSET") if select.args.get("offset") else 0
    limit = compiler.page_integer(select.args["limit"], "LIMIT") if select.args.get("limit") else None
    if offset:
        pipeline.append({"$skip": offset})
    if limit == 0:
        # Mongo $limit:0 is invalid; an always-false match keeps the query empty.
        pipeline.append({"$match": {"$expr": {"$literal": False}}})
    elif limit is not None:
        pipeline.append({"$limit": limit})
    if projection:
        if "_id" not in projection:
            projection["_id"] = 0
        pipeline.append({"$project": projection})
    return MongoQuery(str(selected_database or ""), collection, pipeline, columns, limit == 0)
