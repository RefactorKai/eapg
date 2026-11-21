#include <algorithm>
#include <array>
#include <chrono>
#include <iostream>
#include <limits>
#include <numeric>
#include <string>
#include <vector>

using Clock = std::chrono::steady_clock;
using Kernel = unsigned long long (*)(const int*, const int*, int*, int);
unsigned long long target(const int*, const int*, int*, int);
unsigned long long reference(const int*, const int*, int*, int);
unsigned long long empty(const int*, const int*, int*, int);

int main(int argc, char**) {
    int n;
    std::string order;
    if (!(std::cin >> n >> order) || n < 256 || n > 8192 || order.size() != 11 ||
        order.find_first_not_of("01") != std::string::npos) return 2;
    std::vector<int> data(n), queries(n), expected(n), output(n);
    std::iota(data.begin(), data.end(), 1);
    for (auto& q : queries) if (!(std::cin >> q)) return 2;
    for (auto& rank : expected) if (!(std::cin >> rank)) return 2;

    const std::array<Kernel, 2> kernels{target, reference};
    const auto block = [&](Kernel kernel, int reps) {
        // Verify every request after the clock stops, using a separate preallocated slot.
        std::vector<int> ranks(static_cast<std::size_t>(n) * reps);
        const auto start = Clock::now();
        for (int i = 0; i < reps; ++i)
            kernel(data.data(), queries.data(), ranks.data() + i * n, n);
        const auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
            Clock::now() - start).count();
        if (kernel != empty)
            for (int i = 0; i < reps; ++i)
                if (!std::equal(expected.begin(), expected.end(), ranks.data() + i * n))
                    return -1LL;
        return static_cast<long long>(ns);
    };
#if defined(VALIDATION)
    for (auto kernel : kernels) {
        const auto count = kernel(data.data(), queries.data(), output.data(), n);
        if (output != expected) return 3;
        std::cout << count << '\n';
    }
#else
    static_assert(Clock::is_steady);
    long long tick = std::numeric_limits<long long>::max();
    for (int i = 0; i < 1024; ++i) {
        auto a = Clock::now(), b = Clock::now();
        const auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(b - a).count();
        if (ns > 0) tick = std::min(tick, static_cast<long long>(ns));
    }
    if (tick == std::numeric_limits<long long>::max()) return 4;
    std::cout << tick << '\n';
    int reps = 1;
    const int first = order.front() - '0';
    for (;;) {
        const auto a = block(kernels[first], reps), b = block(kernels[1 - first], reps);
        if (std::min(a, b) < 0 || std::max(a, b) > 500'000'000) return 5;
        std::cout << "pilot " << reps << ' ' << a << ' ' << b << '\n';
        if (std::min(a, b) >= std::max(50'000LL, tick * 100)) break;
        if (reps == 1024) return 6;
        reps *= 2;
    }
    for (std::size_t i = 1; i < order.size(); ++i) {
        const int side = order[i] - '0';
        const auto a = block(kernels[side], reps), b = block(kernels[1 - side], reps);
        const auto control = block(empty, reps);
        if (std::min(a, b) < 0) return 7;
        std::cout << "block " << reps << ' ' << side << ' ' << a << ' ' << b
                  << ' ' << control << '\n';
    }
#endif
    return 0;
}
