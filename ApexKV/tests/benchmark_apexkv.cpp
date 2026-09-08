#include <iostream>
#include <chrono>
#include <string>
#include <unordered_map>
#include "hash_table.hpp"

using namespace std;
using namespace std::chrono;

int main() {
    const int N = 100000;

    // Benchmark HashTable<string, int>
    HashTable<string, int> ht;
    auto start = high_resolution_clock::now();
    for (int i = 0; i < N; ++i) {
        string key = "key" + to_string(i);
        ht.put(key, i);
    }
    auto end = high_resolution_clock::now();
    auto ht_insert_ms = duration_cast<milliseconds>(end - start).count();

    start = high_resolution_clock::now();
    long long dummy = 0;
    for (int i = 0; i < N; ++i) {
        string key = "key" + to_string(i);
        dummy += ht.get(key);
    }
    end = high_resolution_clock::now();
    auto ht_get_ms = duration_cast<milliseconds>(end - start).count();

    // Benchmark unordered_map<string, int>
    unordered_map<string, int> um;
    start = high_resolution_clock::now();
    for (int i = 0; i < N; ++i) {
        string key = "key" + to_string(i);
        um[key] = i;
    }
    end = high_resolution_clock::now();
    auto um_insert_ms = duration_cast<milliseconds>(end - start).count();

    start = high_resolution_clock::now();
    dummy = 0;
    for (int i = 0; i < N; ++i) {
        dummy += um.at("key" + to_string(i));
    }
    end = high_resolution_clock::now();
    auto um_get_ms = duration_cast<milliseconds>(end - start).count();

    cout << "HashTable<string, int> (" << N << " ops):\n";
    cout << "  Insert: " << ht_insert_ms << " ms\n";
    cout << "  Get:    " << ht_get_ms << " ms\n\n";

    cout << "unordered_map<string, int> (" << N << " ops):\n";
    cout << "  Insert: " << um_insert_ms << " ms\n";
    cout << "  Get:    " << um_get_ms << " ms\n";

    return 0;
}
