"""Authored plain and independently counted C++17 weighted-panel sources."""


HEADERS = """#include <algorithm>
#include <cstdio>
#include <vector>
"""
MAIN = """int main() {
    int n, p;
    if (std::scanf("%d%d", &n, &p) != 2 || n < 1) return 1;
"""
SEARCH_SETUP = """    if (p < 0 || p > n) return 1;
    std::vector<int> data(n, 0);
    if (p < n) {
        data[p] = 1;
    }
"""
COMPARISON_COUNTER = """struct Needle {};
static unsigned long long comparisons = 0;
bool operator==(int value, Needle) {
    ++comparisons;
    return value == 1;
}
"""
SWAP_COUNTER = """struct Numbered { int value; };
static unsigned long long swaps = 0;
void swap(Numbered& left, Numbered& right) noexcept {
    ++swaps;
    const int saved = left.value;
    left.value = right.value;
    right.value = saved;
}
"""


def _search(operation, counted):
    needle = "Needle{}" if counted else "1"
    call = f"std::{operation}(data.begin(), data.end(), {needle})"
    if operation == "find":
        update = f"const auto it = {call};\n        checksum += it - data.begin();"
    else:
        update = f"checksum += {call};"
    body = SEARCH_SETUP + f"""    long long checksum = 0;
    for (int i = 0; i < n; ++i) {{
        {update}
    }}
"""
    if counted:
        return HEADERS + COMPARISON_COUNTER + MAIN + body + '    std::printf("%lld %llu\\n", checksum, comparisons);\n}\n'
    return HEADERS + MAIN + body + '    std::printf("%lld\\n", checksum);\n}\n'


def _reverse(counted):
    element = "Numbered" if counted else "int"
    member = ".value" if counted else ""
    body = f"""    std::vector<{element}> data(n);
    for (int i = 0; i < n; ++i) {{
        data[i]{member} = i;
    }}
    long long checksum = 0;
    for (int i = 0; i < n; ++i) {{
        std::reverse(data.begin(), data.end());
        checksum += data.front(){member};
    }}
"""
    if counted:
        return HEADERS + SWAP_COUNTER + MAIN + body + '    std::printf("%lld %llu\\n", checksum, swaps);\n}\n'
    return HEADERS + MAIN + body + '    std::printf("%lld\\n", checksum);\n}\n'


SOURCES = {
    "find": (_search("find", False), _search("find", True)),
    "count": (_search("count", False), _search("count", True)),
    "reverse": (_reverse(False), _reverse(True)),
}
