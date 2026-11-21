"""Exercise the text-only screening rules without dataset files."""

from . import prescreen


def test_include_resolution_and_comments():
    text = ('/*\n#include "ignored.h"\n*/\n#include "local.h"\n#include <pkg/api.h>\n'
            '#include "generated.h"\n#include <bits/stdc++.h>\n// #pragma GCC target("avx2")\n')
    tags = prescreen.source_tags(text, "src/a.cpp", {"src/local.h", "include/pkg/api.h"}, set(range(1, 9)))
    assert [row["resolution"] for row in tags["includes"]] == [
        "patch_relative", "patch_search_root_candidate", "outside_visible_files", "gcc_toolchain_header",
    ]
    assert tags["direct_dependence_lines"] == []


def test_patch_flags_changed_intrinsics_with_side_specific_evidence():
    patch = '@@ -1,2 +1,2 @@\n std::thread existing_worker;\n-return scalar(x);\n+return _mm_add_epi32(x, y);'
    target, target_touched = prescreen.patch_view(patch, "target")
    reference, reference_touched = prescreen.patch_view(patch, "reference")
    target_tags = prescreen.source_tags(target, "a.cpp", {"a.cpp"}, target_touched)
    reference_tags = prescreen.source_tags(reference, "a.cpp", {"a.cpp"}, reference_touched)
    assert target_tags["markers"] == {"concurrency": [2]}
    assert target_tags["direct_dependence_lines"] == []
    assert reference_tags["direct_dependence_lines"] == [3]
