#include <iostream>
#include "persistent_kv.hpp"

int main() {
    PersistentKV kv("apexkv.log", "apexkv.snapshot");

    // Demo: puting  some  random data
    kv.put("name", "Alice");
    kv.put("city", "Mumbai");
    kv.put("age", "22");

    std::cout << "name = " << kv.get("name") << "\n";
    std::cout << "city = " << kv.get("city") << "\n";
    std::cout << "age = " << kv.get("age") << "\n";

    // Saving snapshot
    kv.save_snapshot();
    std::cout << "Snapshot saved.\n";

    // Optionally clearing log after snapshot
    kv.clear_log_after_snapshot();
    std::cout << "Log cleared after snapshot.\n";

    // Removing a key
    kv.remove("city");
    std::cout << "Removed city. Contains city? " 
              << (kv.contains("city") ? "yes" : "no") << "\n";

    // Simulate restart: creat a new PersistentKV instance
    std::cout << "\nSimulating restart...\n";
    PersistentKV kv2("apexkv.log", "apexkv.snapshot");

    std::cout << "After restart:\n";
    std::cout << "name = " << kv2.get("name") << "\n";
    std::cout << "city exists? " << (kv2.contains("city") ? "yes" : "no") << "\n";
    std::cout << "age = " << kv2.get("age") << "\n";

    return 0;
}