#include <algorithm>
#include <iostream>
#include <numeric>
#include <vector>

int main()
{
    int size;
    while (std::cin >> size) {
        if (size < 2 || size > 256) {
            return 2;
        }
        std::vector<int> data(size);
        std::iota(data.begin(), data.end(), 0);
        for (const int key : {0, size / 2, size - 1, size}) {
            int calls = 0;
            const auto hit = std::find_if(data.begin(), data.end(), [key, &calls](int value) {
                ++calls;
                return value == key;
            });
            std::cout << size << ' ' << key << ' ' << (hit - data.begin()) << ' ' << calls << '\n';
        }
    }
}
