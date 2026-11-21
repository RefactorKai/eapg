"""Pinned source transformations and independent workload oracles for five Path B cases."""

from datetime import date, timedelta
from hashlib import sha256
import json
from pathlib import Path
from random import Random


REPO = Path(__file__).resolve().parents[2]
CUSTODY = REPO / ".codex/private/lab/path-b-census"
DRAFT = CUSTODY / "phase-a/ledger-v2-a4-draft.json"
DRAFT_SHA = "29176fea17f9f65273f4d70f2f6cbc420add1dcd1b4cfdc37d20296af7afb00d"
VALIDATION = REPO.parent / ".codex/private/pie-download-VkVck8zh/pie_val.jsonl"
VALIDATION_SHA = "6608a303c5c6ab61e7936599f3aa8cbde67bc36007e1a9739d7868665c531dab"
CASES = {17: "p00256", 60: "p02346", 62: "p03048", 71: "p03999", 137: "leetcode-315"}
VARIANTS = ("target", "reference", "restored", "sham")
EVENTS = {
    17: ["query day-accumulator updates"],
    60: ["nonempty stored query contributions"],
    62: ["candidate residual arithmetic entries", "candidate visits"],
    71: ["input digits decoded during numeric preparation"],
    137: ["combining comparisons", "unchanged rank-search comparisons"],
}


def digest(data):
    return sha256(data).hexdigest()


def pinned(path, expected):
    data = path.read_bytes()
    if digest(data) != expected:
        raise ValueError(f"Unrecognized SHA-256 for {path.name}")
    return data


def originals(row):
    hashes = row["phase_a"]["sources_sha256"]
    if row["intake_rank"] == 137:
        pair, = hashes.values()
        return {side: pinned(CUSTODY / "cppperf-blobs" / pair[key], pair[key])
                for side, key in (("target", "old_sha256"), ("reference", "new_sha256"))}
    dataset = pinned(VALIDATION, VALIDATION_SHA)
    for line in dataset.splitlines():
        record = json.loads(line)
        if (record["problem_id"], record["src_id"], record["tgt_id"]) == (
            row["case_id"], row["target"], row["reference"]
        ):
            sources = {"target": record["src_code"].encode(), "reference": record["tgt_code"].encode()}
            if {side: digest(src) for side, src in sources.items()} != hashes:
                raise ValueError("PIE source bytes do not match the desk receipt")
            return sources
    raise ValueError("The selected validation pair is missing")


COUNTER = b"""
#ifdef PATH_B_COUNT
#include <cstdio>
#include <cstdlib>
#include <unistd.h>
static unsigned long long pb_primary = 0, pb_secondary = 0;
static void pb_write() {
    dprintf(3, "%llu %llu\\n", pb_primary, pb_secondary);
}
struct pb_reporter {
    pb_reporter() { std::atexit(pb_write); }
} pb_report;
static void pb_add(unsigned long long& counter, unsigned long long count) {
    static const auto cap = [] {
        const auto n = std::strtoull(std::getenv("EAPG_N"), nullptr, 10);
        return 5ULL * n * n > 2000000ULL ? 5ULL * n * n : 2000000ULL;
    }();
    counter += count;
    if (pb_primary + pb_secondary >= cap) std::exit(85);
}
#define PB(n) pb_add(pb_primary, n)
#define PB2(n) pb_add(pb_secondary, n)
#else
#define PB(n) ((void)0)
#define PB2(n) ((void)0)
#endif
"""


def at(tree, src, line, kind):
    lines = src.splitlines(keepends=True)
    current = lines[line - 1]
    offset = sum(map(len, lines[:line - 1])) + len(current) - len(current.lstrip())
    node = tree.root_node.descendant_for_byte_range(offset, offset + 1)
    while node is not None and node.start_byte == offset:
        if node.type == kind:
            return node
        node = node.parent
    raise ValueError(f"AST site {line} {kind} is missing")


def edit(src, changes):
    receipt = []
    previous = len(src)
    for start, end, replacement in sorted(changes, key=lambda c: (c[0], c[1]), reverse=True):
        if not 0 <= start <= end <= previous:
            raise ValueError("Overlapping or invalid AST edits")
        receipt.append({"start": start, "end": end, "before_sha256": digest(src[start:end]),
                        "replacement_sha256": digest(replacement)})
        src = src[:start] + replacement + src[end:]
        previous = start
    return src, receipt


def span(node, replacement):
    return node.start_byte, node.end_byte, replacement


def after(node, addition):
    return node.end_byte, node.end_byte, addition


def prepared_sources(rank, sources):
    from tree_sitter import Language, Parser, Query, QueryCursor
    import tree_sitter_cpp

    language = Language(tree_sitter_cpp.language())
    parser = Parser(language)
    variants, plain_sources, maps = {}, {}, {}
    for variant in VARIANTS:
        target = variant != "reference"
        restored = variant == "restored"
        sham = variant == "sham"
        source = sources["target" if target else "reference"]
        src, plain, count = source, [], []
        tree = parser.parse(src)

        def site(line, kind="expression_statement"):
            return at(tree, src, line, kind)

        def node_bytes(node):
            return src[node.start_byte:node.end_byte]

        if rank == 17:
            declaration = site(31, "declaration")
            epoch = site(87 if target else 81)
            count.extend([(0, 0, b"static bool pb_query = false;\n"),
                          after(epoch, b"\npb_query = true;\n")])
            if restored:
                loop = site(33, "for_statement")
                formula = b"int res=(y-1)*365+(y-1)/4-(y-1)/100+(y-1)/400;"
                plain.append((declaration.start_byte, loop.end_byte, formula))
                count.append((declaration.start_byte, loop.end_byte,
                              formula + b" if (pb_query) PB(1);"))
            else:
                count.append(after(declaration, b" if (pb_query) PB(1);"))
                if target:
                    decrement = site(35, "if_statement").child_by_field_name("consequence")
                    count.append(span(decrement, b"{res--; if (pb_query) PB(1);}"))
            month_block = site(39 if target else 33, "for_statement").child_by_field_name("body")
            month_if, = (node for node in month_block.named_children if node.type == "if_statement")
            leap = month_if.child_by_field_name("consequence")
            count.extend([after(month_block.named_children[0], b" if (pb_query) PB(1);"),
                          span(leap, b"{res++; if (pb_query) PB(1);}")])
            if sham:
                result = site(45, "return_statement")
                plain.append(span(result, b"return res+d+0;"))

        elif rank == 60:
            if target:
                root = site(471, "return_statement")
                count.append(span(root, b"{ PB(1); " + node_bytes(root) + b" }"))
                count.extend([(expr.start_byte, expr.start_byte, statement)
                              for expr, statement in ((site(297), b"PB(1 + (n->right != &nil)); "),
                                                      (site(319), b"PB(1 + (n->left != &nil)); "))])
                guard = site(461, "if_statement")
                if restored:
                    plain.append(after(guard, b"\nif (begin == 0 && end == root_->size) return root_->sum;"))
                    count.append(after(guard, b"\nif (begin == 0 && end == root_->size) { PB(1); return root_->sum; }"))
                if sham:
                    plain.append(span(guard, b"if (begin >= end + 0) return Monoid();"))
            else:
                body = site(121, "do_statement").child_by_field_name("body")
                count.append(span(body, b"{ if (end != 0) PB(1); " + node_bytes(body) + b" }"))

        elif rank == 62:
            loop = site(13 if target else 21, "for_statement").child_by_field_name("body")
            count.append((loop.start_byte + 1, loop.start_byte + 1, b" PB2(1); "))
            if target:
                condition = site(15, "if_statement")
                if restored:
                    fix = b"const int remaining=n-i*r-j*g; if(remaining>=0) { if(remaining%b==0) ++ans; }"
                    plain.append(span(condition, fix))
                    count.append(span(condition, fix.replace(b"if(remaining%b", b"PB(1); if(remaining%b")))
                else:
                    count.append((condition.start_byte, condition.start_byte, b"PB(1); "))
                    if sham:
                        plain.append(span(condition, b"const int remaining=n-i*r-j*g;\n"
                                          b"if(remaining/b>=0 && i*r+j*g+b*(remaining/b)==n) ++ans;"))
            else:
                block = site(25, "if_statement").child_by_field_name("consequence")
                count.append((block.start_byte + 1, block.start_byte + 1, b" PB(1); "))

        elif rank == 71:
            if target and restored:
                loop = site(47, "for_statement")
                decode = b"int digits[15]; for(int i=0;i<n;++i){ digits[i]=s[i]-'0'; }"
                fill = b"for(int i=0;i<n;++i){ ll v=0; for(int j=i;j<n;++j){v=10*v+digits[j];num[i][j]=v;} }"
                plain.append(span(loop, decode + fill))
                count.append(span(loop, decode.replace(b"digits[i]", b"PB(1); digits[i]") + fill))
            elif target:
                parse = site(59)
                count.append(span(parse, b"size_t consumed=0; num[i][j]=stoll(t,&consumed,10);"
                                  b"if(consumed!=t.size()) std::abort(); PB(consumed);"))
                if sham:
                    plain.append(span(parse, b"num[i][j]=stoll(t,nullptr,10);"))
            else:
                body = site(61, "for_statement").child_by_field_name("body")
                count.append(span(body, b"{ PB(1); " + node_bytes(body) + b" }"))

        else:
            query = Query(language, "(call_expression function: (identifier) @function) @call")
            calls = {node_bytes(match["function"][0]): match["call"][0]
                     for _, match in QueryCursor(query).matches(tree.root_node)}
            op = calls[b"sort" if target else b"inplace_merge"]
            endpoint = b"sortedNums.begin()+end+1"
            start = b"sortedNums.begin()+start"
            middle = b"sortedNums.begin()+mid+1"
            prefix = b""
            if sham:
                statement = op.parent
                prefix = b"const auto first=" + start + b", last=" + endpoint + b"; "
                plain.append(span(statement, prefix + b"sort(first,last);"))
                count.append(span(statement, prefix + b"sort(first,last,"
                                  b"[](int a,int b){PB(1);return a<b;});"))
            else:
                call = (b"inplace_merge(" + start + b"," + middle + b"," + endpoint
                        if restored or not target else b"sort(" + start + b"," + endpoint)
                if restored:
                    plain.append(span(op, call + b")"))
                count.append(span(op, call + b",[](int a,int b){PB(1);return a<b;})"))
            lower = calls[b"lower_bound"].child_by_field_name("arguments")
            count.append((lower.end_byte - 1, lower.end_byte - 1,
                          b",[](int a,int b){PB2(1);return a<b;}"))

        changes = [c for c in plain if not any(c[:2] == instrumentation[:2] for instrumentation in count)]
        plain_sources[variant], intervention = edit(src, plain)
        variants[variant], instrumentation = edit(src, count + changes)
        if rank == 137:
            header = b"#include <algorithm>\n#include <iostream>\n#include <vector>\nusing namespace std;\n"
            harness = b"""
int main() {
    int n;
    if (!(cin >> n) || n < 1) return 2;
    vector<int> v(n);
    for (int& x : v) if (!(cin >> x)) return 2;
    const auto old = v;
    const auto answer = Solution{}.countSmaller(v);
    if (v != old) return 3;
    for (int x : answer) cout << x << '\\n';
}
"""
            plain_sources[variant] = header + plain_sources[variant] + harness
            variants[variant] = header + variants[variant] + harness
        variants[variant] = COUNTER + variants[variant]
        maps[variant] = {"plain_edits": intervention, "counted_edits": instrumentation,
                         "original_sha256": digest(source),
                         "plain_sha256": digest(plain_sources[variant]),
                         "instrumented_sha256": digest(variants[variant])}
    return plain_sources, variants, maps


def calendar(item):
    epoch = date(2012, 12, 21)
    units = (144000, 7200, 360, 20, 1)
    if len(item) == 5:
        days = sum(a * b for a, b in zip(item, units, strict=True))
        output = epoch + timedelta(days=days)
        return f"{output.year}.{output.month}.{output.day}"
    y, m, d = item
    cycles, residual = divmod(y - 1, 400)
    days = ((date(residual + 1, m, d) - epoch).days + cycles * 146097) % 1872000
    digits = []
    for unit in units:
        amount, days = divmod(days, unit)
        digits.append(amount)
    return ".".join(map(str, digits))


def workload(rank, source_row):
    registration = source_row["phase_a"]["proposed_workload"]
    sizes, streams = registration["sizes"], registration["streams"]
    samples = []

    def add(stream, size, data, outputs, checks=None):
        samples.append({"stream": stream, "size": size, "input": data,
                        "expected": list(map(str, outputs)), "checks": checks})

    if rank == 17:
        def batch(stream, n, items):
            add(stream, n, "\n".join(".".join(map(str, item)) for item in items) + "\n#\n",
                (calendar(item) for item in items))
        for stream, month in zip(streams, (1, 7, 12), strict=True):
            for n in sizes:
                batch(stream, n, [(n, month, 1)])
                # The independent calendar oracle above supplies output validity. Count calibration uses
                # the number of prior non-leap centuries and month accumulator writes.
                common = month + int(month > 2 and n % 4 == 0 and (n % 100 != 0 or n % 400 == 0))
                slow = common + (n - 1) // 100 - (n - 1) // 400
                samples[-1]["checks"] = [slow, common, common, slow]
        batch("challenge", 10_000_000, [(2012, 12, 21), (2100, 2, 28), (2100, 3, 1),
              (2400, 2, 29), (2, 12, 16, 14, 14), (7138, 5, 13), (10_000_000, 12, 31)])
    elif rank == 60:
        def range_batch(stream, n, ops):
            state, outputs = [0] * n, []
            for command, x, y in ops:
                if command == 0:
                    state[x - 1] += y
                else:
                    outputs.append(sum(state[x - 1:y]))
            add(stream, n, f"{n} {len(ops)}\n" + "".join(f"{c} {x} {y}\n" for c, x, y in ops), outputs)
        for i, stream in enumerate(streams):
            for n in sizes:
                indices = ([1] * n, range(1, n + 1), [1, n] * (n // 2))[i]
                range_batch(stream, n, [op for j in indices for op in ((0, j, i + 1), (1, 1, n))])
                samples[-1]["checks"] = [None, n, n, None]
        range_batch("challenge", 3, [(1, 1, 3), (0, 1, 1), (0, 2, 2), (0, 3, 3),
                                     (1, 1, 2), (1, 2, 2), (0, 2, 0), (1, 2, 3)])
        range_batch("challenge", 1, [(1, 1, 1), (0, 1, 1000), (1, 1, 1)])
    elif rank == 62:
        def rgb(stream, n, r, g, b):
            # Enumerate independent red and blue choices, then solve for green.
            output = sum((n - x - z) % g == 0 for x in range(0, n + 1, r)
                         for z in range(0, n - x + 1, b))
            add(stream, n, f"{r} {g} {b} {n}\n", [output])
        for i, stream in enumerate(streams):
            for n in sizes:
                r, g, b = ((n, n, 1), (n // 2, n, 2), (n // 4, n // 2, 3))[i]
                rgb(stream, n, r, g, b)
                feasible = sum(1 + (n - a) // g for a in range(0, n + 1, r))
                visits = (n + 1) ** 2
                samples[-1]["checks"] = [visits, feasible, feasible, visits]
        for n, r, g, b in [(15, 4, 3, 2), (5, 3, 3, 3), (3000, 3000, 2999, 17)]:
            rgb("challenge", n, r, g, b)
    elif rank == 71:
        def formula(stream, digits):
            total = 0
            n = len(digits)
            for mask in range(1 << (n - 1)):
                cut = [0, *(i for i in range(1, n) if mask & (1 << (i - 1))), n]
                total += sum(int(digits[a:b]) for a, b in zip(cut, cut[1:]))
            repeated = n * (n + 1) * (n + 2) // 6
            add(stream, n, digits + "\n", [total], [repeated, n, n, repeated])
        for i, stream in enumerate(streams):
            for n in sizes:
                formula(stream, ("1" * n, "9" * n, ("27" * n)[:n])[i])
        for digits in ("125", "1234567891", "7"):
            formula("challenge", digits)
    else:
        def suffix_ranks(stream, values):
            n = len(values)
            output = [sum(other < x for other in values[i + 1:]) for i, x in enumerate(values)]
            add(stream, n, f"{n}\n" + " ".join(map(str, values)) + "\n", output)
        for i, stream in enumerate(streams):
            for n in sizes:
                bits = n.bit_length() - 1
                values = list(range(n))
                if i == 0:
                    values = [int(f"{j:0{bits}b}"[::-1], 2) for j in values]
                elif i == 1:
                    Random(42 + n).shuffle(values)
                else:
                    rng = Random(73 + n)
                    values = [rng.randrange(-8, 9) for _ in values]
                suffix_ranks(stream, values)
        for values in ([5, 2, 6, 1], [-10000, 10000, -10000], [2] * 16, [0]):
            suffix_ranks("challenge", values)
    return samples
