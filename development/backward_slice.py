"""Conventional static backward slicing for an intraprocedural C++17 subset.

Input is compiler-validated source with normalized braces and one `int main()`.
The subset has automatic integral scalars, lexical blocks, runtime if/else,
for with an explicit test, while/do, break/continue, and return. Operands may
contain pure scalar expressions and integral static_cast. Assignment and
increment are standalone effects (also valid in for headers). Tests model
short-circuit edges. Branch feasibility is conservative.

The only header allowed is <cstdio>. Modeled calls are std::scanf("%d", &x)
for a mutable plain int as a statement or predicate atom (optionally compared
to a constant), and standalone std::printf with one scalar local or integral
cast matching literal %d or %lld, optionally followed by a newline. A failed
scan may leave the old value. Other calls, aliases, globals, memory operations,
and unsupported syntax raise UnsupportedProgram for the case.

Each canonical span owns the CFG operations for that AST statement or control
header. Unmapped operations participate in dependence closure. Results contain
only canonical IDs, in the supplied order.
"""

from collections import defaultdict
from typing import NamedTuple


class UnsupportedProgram(ValueError):
    """The source or canonical criterion is outside the comparator's domain."""


def named(node):
    return [child for child in node.named_children if child.type != "comment"]


def span(node):
    return (node.start_byte, node.end_byte)


def unsupported(node):
    raise UnsupportedProgram(f"Unsupported {node.type} on normalized line {node.start_point.row + 1}")


def integral(node):
    return node is not None and (
        node.type == "primitive_type" and node.text in (b"int", b"bool", b"char")
        or node.type == "sized_type_specifier"
        and all(child.text in (b"signed", b"unsigned", b"short", b"long", b"int", b"char")
                for child in node.children if child.type != "comment")
    )


def print_conversion(declared_type):
    tokens = [child.text for child in declared_type.children if child.type != "comment"]
    if declared_type.text == b"int" or tokens == [b"signed"] or set(tokens) == {b"signed", b"int"}:
        return b"%d"
    if tokens.count(b"long") == 2 and all(token in (b"signed", b"long", b"int") for token in tokens):
        return b"%lld"
    return None


def integral_cast(node):
    if node.type == "call_expression":
        callee = node.child_by_field_name("function")
        if callee.type == "template_function" and callee.child_by_field_name("name").text == b"static_cast":
            types = named(callee.child_by_field_name("arguments"))
            args = named(node.child_by_field_name("arguments"))
            if len(types) == len(args) == 1 and types[0].type == "type_descriptor":
                cast_type = types[0].child_by_field_name("type")
                if integral(cast_type) and named(types[0]) == [cast_type]:
                    return cast_type, args[0]
    return None


class Operation(NamedTuple):
    owner: tuple[int, int] | None
    uses: frozenset[int]
    kills: frozenset[int]
    defines: frozenset[int]


class ControlFlow:
    def __init__(self):
        self.operations = []
        self.successors = []
        self.scopes = []
        self.scan_targets = set()
        self.print_conversions = {}
        self.entry = self.emit(())
        self.exit = self.emit(())

    def connect(self, incoming, target):
        for source in incoming:
            self.successors[source].add(target)

    def emit(self, incoming, owner=None, uses=(), kills=(), defines=()):
        index = len(self.operations)
        self.operations.append(Operation(span(owner) if owner else None, frozenset(uses),
                                         frozenset(kills), frozenset(defines)))
        self.successors.append(set())
        self.connect(incoming, index)
        return index

    def binding(self, node):
        if node.type == "identifier":
            for scope in reversed(self.scopes):
                if node.text in scope:
                    return scope[node.text]
        unsupported(node)

    def value(self, node):
        if node.type == "identifier":
            return {self.binding(node)}
        if node.type in ("number_literal", "char_literal", "true", "false"):
            return set()
        if node.type == "parenthesized_expression":
            operand, = named(node)
            return self.value(operand)
        if node.type == "unary_expression" and node.child_by_field_name("operator").type in ("+", "-", "!", "~"):
            return self.value(node.child_by_field_name("argument"))
        if node.type == "binary_expression" and node.child_by_field_name("operator").type in (
            "+", "-", "*", "/", "%", "<", ">", "<=", ">=", "==", "!=", "<<", ">>",
            "&", "|", "^", "&&", "||",
        ):
            return self.value(node.child_by_field_name("left")) | self.value(node.child_by_field_name("right"))
        cast = integral_cast(node)
        if cast:
            return self.value(cast[1])
        unsupported(node)

    def std_call(self, node, name):
        if node.type != "call_expression":
            return None
        callee = node.child_by_field_name("function")
        if callee.type == "qualified_identifier":
            scope = callee.child_by_field_name("scope")
            target = callee.child_by_field_name("name")
            if scope and scope.text == b"std" and target.type == "identifier" and target.text == name:
                return named(node.child_by_field_name("arguments"))
        return None

    def scan_target(self, node):
        args = self.std_call(node, b"scanf")
        if args is None:
            return None
        if len(args) == 2 and args[0].type == "string_literal" and args[0].text == b'"%d"':
            address = args[1]
            if address.type == "pointer_expression" and address.child_by_field_name("operator").type == "&":
                binding = self.binding(address.child_by_field_name("argument"))
                if binding in self.scan_targets:
                    return binding
        unsupported(node)

    def declaration(self, node, incoming, owner):
        declared_type = node.child_by_field_name("type")
        declarators = node.children_by_field_name("declarator")
        qualifiers = [child for child in named(node) if child.type == "type_qualifier"]
        if (not integral(declared_type) or not declarators
                or any(child not in declarators + qualifiers + [declared_type] for child in named(node))
                or any(child.text not in (b"const", b"volatile") for child in qualifiers)):
            unsupported(node)
        scope = self.scopes[-1]
        for declarator in declarators:
            value = None
            name = declarator
            if declarator.type == "init_declarator":
                name = declarator.child_by_field_name("declarator")
                value = declarator.child_by_field_name("value")
            if name.type != "identifier" or name.text in scope:
                unsupported(declarator)
            binding = name.start_byte
            scope[name.text] = binding
            self.print_conversions[binding] = print_conversion(declared_type)
            if declared_type.text == b"int" and not qualifiers:
                self.scan_targets.add(binding)
            if value and value.type in ("initializer_list", "argument_list"):
                values = named(value)
                if len(values) > 1:
                    unsupported(value)
                uses = self.value(values[0]) if values else set()
            else:
                uses = self.value(value) if value else set()
            incoming = [self.emit(incoming, owner, uses, (binding,), (binding,) if value else ())]
        return incoming

    def effect(self, node, incoming, owner):
        if node.type == "assignment_expression":
            target = self.binding(node.child_by_field_name("left"))
            uses = self.value(node.child_by_field_name("right"))
            if node.child_by_field_name("operator").type != "=":
                uses.add(target)
            return self.emit(incoming, owner, uses, (target,), (target,))
        if node.type == "update_expression":
            target = self.binding(node.child_by_field_name("argument"))
            return self.emit(incoming, owner, (target,), (target,), (target,))
        target = self.scan_target(node)
        if target is not None:
            return self.emit(incoming, owner, defines=(target,))
        args = self.std_call(node, b"printf")
        if args is not None:
            if len(args) != 2 or args[0].type != "string_literal":
                unsupported(node)
            argument = args[1]
            while argument.type == "parenthesized_expression":
                argument, = named(argument)
            cast = integral_cast(argument)
            if cast:
                conversion = print_conversion(cast[0])
            elif argument.type == "identifier":
                conversion = self.print_conversions[self.binding(argument)]
            else:
                conversion = None
            if conversion is None or args[0].text not in (b'"' + conversion + b'"', b'"' + conversion + b'\\n"'):
                unsupported(node)
            return self.emit(incoming, owner, self.value(argument))
        return self.emit(incoming, owner, self.value(node))

    def condition(self, node, incoming, owner):
        if node.type in ("parenthesized_expression", "condition_clause"):
            parts = named(node)
            if len(parts) != 1 or (node.type == "condition_clause" and node.child_by_field_name("value") != parts[0]):
                unsupported(node)
            return self.condition(parts[0], incoming, owner)
        target = self.scan_target(node)
        if node.type == "binary_expression":
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            operator = node.child_by_field_name("operator").type
            if operator == "&&":
                yes, no = self.condition(left, incoming, owner)
                right_yes, right_no = self.condition(right, yes, owner)
                return right_yes, no + right_no
            if operator == "||":
                yes, no = self.condition(left, incoming, owner)
                right_yes, right_no = self.condition(right, no, owner)
                return yes + right_yes, right_no
            if operator in ("==", "!=", "<", ">", "<=", ">=") and right.type == "number_literal":
                target = self.scan_target(left)
        if node.type == "unary_expression" and node.child_by_field_name("operator").type == "!":
            yes, no = self.condition(node.child_by_field_name("argument"), incoming, owner)
            return no, yes
        index = (self.emit(incoming, owner, defines=(target,)) if target is not None
                 else self.emit(incoming, owner, self.value(node)))
        return [index], [index]

    def block(self, node, incoming, loop=None):
        if node.type != "compound_statement":
            unsupported(node)
        self.scopes.append({})
        for child in named(node):
            incoming = self.statement(child, incoming, loop)
        self.scopes.pop()
        return incoming

    def loop(self, node, incoming):
        self.scopes.append({})
        condition = node.child_by_field_name("condition")
        if condition is None:
            unsupported(node)
        init = node.child_by_field_name("initializer")
        if init and init.type != "null_statement":
            if init.type == "declaration":
                incoming = self.declaration(init, incoming, node)
            else:
                incoming = [self.effect(init, incoming, node)]
        after = self.emit(())
        update = node.child_by_field_name("update")
        do_while = node.type == "do_statement"
        test_head = self.emit(() if do_while else incoming)
        update_head = self.emit(()) if update else test_head
        yes, no = self.condition(condition, [test_head], node)
        body = self.block(node.child_by_field_name("body"), incoming + yes if do_while else yes,
                          (after, update_head))
        self.connect(body, update_head)
        if update:
            self.connect((self.effect(update, [update_head], node),), test_head)
        self.connect(no, after)
        self.scopes.pop()
        return [after]

    def statement(self, node, incoming, loop):
        kind = node.type
        if kind == "compound_statement":
            return self.block(node, incoming, loop)
        if kind == "declaration":
            return self.declaration(node, incoming, node)
        if kind == "expression_statement":
            expressions = named(node)
            return [self.effect(expressions[0], incoming, node)] if expressions else incoming
        if kind == "return_statement":
            value, = named(node)
            self.connect((self.emit(incoming, node, self.value(value)),), self.exit)
            return []
        if kind == "if_statement":
            if any(child.type == "constexpr" for child in node.children):
                unsupported(node)
            yes, no = self.condition(node.child_by_field_name("condition"), incoming, node)
            yes = self.block(node.child_by_field_name("consequence"), yes, loop)
            alternative = node.child_by_field_name("alternative")
            if alternative:
                other, = named(alternative)
                no = self.block(other, no, loop)
            return yes + no
        if kind in ("for_statement", "while_statement", "do_statement"):
            return self.loop(node, incoming)
        if kind in ("break_statement", "continue_statement") and loop:
            target = loop[0] if kind == "break_statement" else loop[1]
            self.connect((self.emit(incoming, node),), target)
            return []
        unsupported(node)

    def build(self, root):
        if root.has_error:
            raise UnsupportedProgram("Normalized source has a C++ parse error")
        functions = []
        for node in named(root):
            if node.type == "preproc_include" and node.child_by_field_name("path").text == b"<cstdio>":
                continue
            if node.type != "function_definition":
                unsupported(node)
            functions.append(node)
        if len(functions) != 1:
            raise UnsupportedProgram("Expected one int main() definition")
        function = functions[0]
        declared_type = function.child_by_field_name("type")
        declarator = function.child_by_field_name("declarator")
        body = function.child_by_field_name("body")
        if (declared_type is None or declared_type.text != b"int" or declarator.type != "function_declarator"
                or not body or named(function) != [declared_type, declarator, body]):
            unsupported(function)
        name = declarator.child_by_field_name("declarator")
        parameters = declarator.child_by_field_name("parameters")
        if (name.type != "identifier" or name.text != b"main" or parameters is None
                or named(parameters) or named(declarator) != [name, parameters]):
            unsupported(declarator)
        self.connect(self.block(body, [self.entry]), self.exit)

    def dependencies(self):
        reachable = closure([self.entry], self.successors)
        if self.exit not in reachable:
            raise UnsupportedProgram("The CFG has no reachable exit")
        predecessors = defaultdict(set)
        for index in sorted(reachable):
            for target in self.successors[index]:
                predecessors[target].add(index)

        reaching = {index: set() for index in reachable}
        after = {index: set() for index in reachable}
        indices = sorted(reachable)
        changed = True
        while changed:
            changed = False
            for index in indices:
                op = self.operations[index]
                reaching[index] = set().union(*(after[pred] for pred in predecessors[index]))
                transferred = {(name, definition) for name, definition in reaching[index] if name not in op.kills}
                transferred.update((name, index) for name in op.defines)
                if transferred != after[index]:
                    after[index] = transferred
                    changed = True

        postdom = {index: reachable.copy() for index in reachable}
        postdom[self.exit] = {self.exit}
        changed = True
        while changed:
            changed = False
            for index in reversed(indices):
                if index == self.exit:
                    continue
                dominating = set.intersection(*(postdom[target] for target in self.successors[index])) | {index}
                if dominating != postdom[index]:
                    postdom[index] = dominating
                    changed = True

        dependencies = {index: {definition for name, definition in reaching[index]
                                if name in self.operations[index].uses} for index in reachable}
        for index in indices:
            for target in self.successors[index]:
                # The edge forces execution of nodes absent from the predecessor's postdominators.
                for dependent in postdom[target] - postdom[index]:
                    dependencies[dependent].add(index)
        return dependencies


def closure(seeds, edges):
    pending = list(seeds)
    reached = set()
    while pending:
        node = pending.pop()
        if node not in reached:
            reached.add(node)
            pending.extend(edges[node] - reached)
    return reached


def backward_slice(pipeline, normalized, nodes, symptom):
    """Return the conventional dependence closure projected in canonical order."""
    if symptom is None:
        return []
    source = normalized.encode("utf-8")
    canonical = {}
    for node in nodes:
        node_id = node.get("id")
        bounds = node.get("normalized_span")
        if (not isinstance(node_id, str) or not node_id or node_id in canonical
                or not isinstance(bounds, (list, tuple)) or len(bounds) != 2
                or any(type(bound) is not int for bound in bounds)
                or not 0 <= bounds[0] < bounds[1] <= len(source)):
            raise UnsupportedProgram("Invalid canonical ID or normalized span")
        canonical[node_id] = tuple(bounds)
    if symptom not in canonical or len(set(canonical.values())) != len(canonical):
        raise UnsupportedProgram("Missing or ambiguous canonical slicing criterion")
    cfg = ControlFlow()
    cfg.build(pipeline.parser.parse(source).root_node)
    dependencies = cfg.dependencies()
    criterion = [index for index in dependencies if cfg.operations[index].owner == canonical[symptom]]
    if not criterion:
        raise UnsupportedProgram("The canonical symptom has no reachable CFG operation")
    reached = closure(criterion, dependencies)
    spans = {cfg.operations[index].owner for index in reached}
    return [node_id for node_id, bounds in canonical.items() if bounds in spans]
