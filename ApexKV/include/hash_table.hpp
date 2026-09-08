#ifndef HASH_TABLE_HPP
#define HASH_TABLE_HPP

#include <cstddef>
#include <unordered_map>
#include <forward_list>
#include <functional>
#include <utility>

template <typename Key, typename Value>
class HashTable {
private:
    using Pair = std::pair<Key, Value>;

    std::forward_list<Pair>* buckets_;
    std::size_t capacity_;
    std::size_t size_;
    double max_load_factor_;

    std::size_t hash_func(const Key& key) const {
        return std::hash<Key>{}(key) % capacity_;
    }

    void rehash() {
        std::size_t new_capacity = capacity_ * 2;

        auto* new_buckets = new std::forward_list<Pair>[new_capacity];

        for (std::size_t i = 0; i < capacity_; ++i) {
            for (const auto& item : buckets_[i]) {
                std::size_t index = std::hash<Key>{}(item.first) % new_capacity;
                new_buckets[index].push_front(item);
            }
        }

        delete[] buckets_;
        buckets_ = new_buckets;
        capacity_ = new_capacity;
    }

public:
    HashTable()
        : capacity_(16),
          size_(0),
          max_load_factor_(0.75) {
        buckets_ = new std::forward_list<Pair>[capacity_];
    }

    ~HashTable() {
        delete[] buckets_;
    }

    void put(const Key& key, const Value& value) {
        std::size_t index = hash_func(key);

        for (auto& item : buckets_[index]) {
            if (item.first == key) {
                item.second = value;
                return;
            }
        }

        buckets_[index].push_front({key, value});
        ++size_;

        if (load_factor() > max_load_factor_) {
            rehash();
        }
    }

    Value get(const Key& key) const {
        std::size_t index = hash_func(key);

        for (const auto& item : buckets_[index]) {
            if (item.first == key) {
                return item.second;
            }
        }

        return Value{};
    }

    bool contains(const Key& key) const {
        std::size_t index = hash_func(key);

        for (const auto& item : buckets_[index]) {
            if (item.first == key) {
                return true;
            }
        }

        return false;
    }

    bool remove(const Key& key) {
        std::size_t index = hash_func(key);
        auto& bucket = buckets_[index];
        auto previous = bucket.before_begin();

        for (auto current = bucket.begin(); current != bucket.end(); ++current) {
            if (current->first == key) {
                bucket.erase_after(previous);
                --size_;
                return true;
            }

            previous = current;
        }

        return false;
    }

    std::size_t getSize() const {
        return size_;
    }

    double load_factor() const {
        return static_cast<double>(size_) / static_cast<double>(capacity_);
    }

 void collect_all_into(std::unordered_map<Key, Value>& out) const {
    for (std::size_t i = 0; i < capacity_; ++i) {
        for (const auto& pair : buckets_[i]) {
            out[pair.first] = pair.second;
        }
    }
}
};

#endif