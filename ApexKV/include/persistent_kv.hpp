#pragma once
#include <string>
#include <unordered_map>
#include <fstream>
#include <sstream>
#include <iostream>
#include "hash_table.hpp"

class PersistentKV {
public:
    PersistentKV(const std::string& log_path, const std::string& snapshot_path)
        : log_path_(log_path), snapshot_path_(snapshot_path) {
        load();
    }

    void put(const std::string& key, const std::string& value) {
        data_.put(key, value);
        append_log("PUT", key, value);
    }

    std::string get(const std::string& key) const {
        return data_.get(key);
    }

    bool contains(const std::string& key) const {
        return data_.contains(key);
    }

    bool remove(const std::string& key) {
        bool removed = data_.remove(key);
        if (removed) {
            append_log("DEL", key, "");
        }
        return removed;
    }

    // Save current state to a snapshot file
    void save_snapshot() {
        std::ofstream out(snapshot_path_, std::ios::trunc);
        if (!out) {
            std::cerr << "Failed to open snapshot file: " << snapshot_path_ << "\n";
            return;
        }

        std::unordered_map<std::string, std::string> flat;
        collect_all_into(flat);

        for (const auto& [key, value] : flat) {
            out << "PUT " << key << " " << value << "\n";
        }
        out.close();
    }

    // Load from snapshot + log
    void load() {
        // First, load snapshot if it exists
        std::ifstream snap_in(snapshot_path_);
        if (snap_in) {
            std::string line;
            while (std::getline(snap_in, line)) {
                if (line.empty()) continue;
                std::istringstream iss(line);
                std::string op, key, value;
                iss >> op >> key;
                if (op == "PUT") {
                    std::getline(iss >> std::ws, value);
                    data_.put(key, value);
                } else if (op == "DEL") {
                    data_.remove(key);
                }
            }
            snap_in.close();
        }

        // Then replay log
        std::ifstream log_in(log_path_);
        if (!log_in) return;

        std::string line;
        while (std::getline(log_in, line)) {
            if (line.empty()) continue;
            std::istringstream iss(line);
            std::string op, key, value;
            iss >> op >> key;
            if (op == "PUT") {
                std::getline(iss >> std::ws, value);
                data_.put(key, value);
            } else if (op == "DEL") {
                data_.remove(key);
            }
        }
        log_in.close();
    }

    // Optional: after saving snapshot, you can clear the log
    void clear_log_after_snapshot() {
        std::ofstream out(log_path_, std::ios::trunc);
        if (!out) {
            std::cerr << "Failed to truncate log file: " << log_path_ << "\n";
        }
        out.close();
    }

private:
    std::string log_path_;
    std::string snapshot_path_;
    HashTable<std::string, std::string> data_;

    void append_log(const std::string& op, const std::string& key, const std::string& value) {
        std::ofstream out(log_path_, std::ios::app);
        if (!out) {
            std::cerr << "Failed to open log file: " << log_path_ << "\n";
            return;
        }
        out << op << " " << key;
        if (op == "PUT") {
            out << " " << value;
        }
        out << "\n";
        out.close();
    }

    void collect_all_into(std::unordered_map<std::string, std::string>& out) {
        data_.collect_all_into(out);
    }
};