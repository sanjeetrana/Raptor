#include <cstdio>
#include <iostream>
#include <string>

#include "hash_table.hpp"
#include "persistent_kv.hpp"

void test_int_values() {
    HashTable<std::string, int> ht;

    ht.put("age", 25);
    ht.put("score", 100);

    if (ht.get("age") != 25 || ht.get("score") != 100) {
        std::cout << "FAIL: int values\n";
        return;
    }

    std::cout << "PASS: int values\n";
}

void test_string_values() {
    HashTable<std::string, std::string> ht;

    ht.put("name", "Alice");
    ht.put("city", "Mumbai");
    ht.put("name", "Bob");

    if (ht.get("name") != "Bob") {
        std::cout << "FAIL: string update\n";
        return;
    }

    if (ht.get("city") != "Mumbai") {
        std::cout << "FAIL: string value\n";
        return;
    }

    std::cout << "PASS: string values\n";
}

void test_int_keys() {
    HashTable<int, std::string> ht;

    ht.put(1, "Delhi");
    ht.put(2, "Mumbai");
    ht.put(3, "Bengaluru");

    if (ht.get(2) != "Mumbai") {
        std::cout << "FAIL: int keys\n";
        return;
    }

    std::cout << "PASS: int keys\n";
}

void test_contains_and_remove() {
    HashTable<std::string, int> ht;

    ht.put("a", 10);
    ht.put("b", 20);

    if (!ht.contains("a")) {
        std::cout << "FAIL: contains existing key\n";
        return;
    }

    if (ht.contains("missing")) {
        std::cout << "FAIL: contains missing key\n";
        return;
    }

    if (!ht.remove("a")) {
        std::cout << "FAIL: remove existing key\n";
        return;
    }

    if (ht.contains("a")) {
        std::cout << "FAIL: key still exists after remove\n";
        return;
    }

    if (ht.remove("missing")) {
        std::cout << "FAIL: remove missing key\n";
        return;
    }

    std::cout << "PASS: contains and remove\n";
}

void test_rehash() {
    HashTable<std::string, int> ht;

    for (int i = 0; i < 50; ++i) {
        ht.put("key" + std::to_string(i), i * 10);
    }

    if (ht.getSize() != 50) {
        std::cout << "FAIL: rehash size\n";
        return;
    }

    for (int i = 0; i < 50; ++i) {
        std::string key = "key" + std::to_string(i);

        if (ht.get(key) != i * 10) {
            std::cout << "FAIL: rehash data for " << key << "\n";
            return;
        }
    }

    std::cout << "PASS: rehash\n";
}

void test_persistence() {
    const std::string test_file = "test_apexkv.log";

    std::remove(test_file.c_str());

    {
        PersistentKV store(test_file);

        store.put("name", "Alice");
        store.put("city", "Mumbai");
        store.put("language", "C++");
        store.remove("city");
    }

    {
        PersistentKV store(test_file);

        if (store.get("name") != "Alice") {
            std::cout << "FAIL: persistence name\n";
            std::remove(test_file.c_str());
            return;
        }

        if (store.contains("city")) {
            std::cout << "FAIL: persistence remove\n";
            std::remove(test_file.c_str());
            return;
        }

        if (store.get("language") != "C++") {
            std::cout << "FAIL: persistence language\n";
            std::remove(test_file.c_str());
            return;
        }
    }

    std::remove(test_file.c_str());
    std::cout << "PASS: persistence\n";
}

int main() {
    test_int_values();
    test_string_values();
    test_int_keys();
    test_contains_and_remove();
    test_rehash();
    test_persistence();

    return 0;
}