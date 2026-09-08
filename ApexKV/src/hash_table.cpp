#include "hash_table.hpp"

HashTable::HashTable()
    : capacity_(16),
      size_(0),
      max_load_factor_(0.75)
{
    buckets_ = new std::forward_list<std::pair<std::string, int>>[capacity_];
}

HashTable::~HashTable() {
    delete[] buckets_;
}

void HashTable::put(const std::string& key, int value) 
{
    size_t idx = hash_func(key);

    // Check if key already exists
    for (auto& kv : buckets_[idx]) {
        if (kv.first == key) {
            kv.second = value;  // update value
            return;
        }
    }

    // New key insert
    buckets_[idx].push_front({key, value});
    ++size_;

    // Resize check
    if (load_factor() > max_load_factor_) 
    {
        rehash();
    }
}

int HashTable::get(const std::string& key) const 
{
    size_t idx = hash_func(key);

    for (const auto& kv : buckets_[idx]) 
    {
        if (kv.first == key) 
        {
            return kv.second;
        }
    }

    return -1;  // not found
}

void HashTable::remove(const std::string& key) 
{
    size_t idx = hash_func(key);

    auto& bucket = buckets_[idx];
    auto prev = bucket.before_begin();

    for (auto it = bucket.begin(); it != bucket.end(); ++it) 
    {
        if (it->first == key) 
        {
            bucket.erase_after(prev);
            --size_;
            return;
        }
        prev = it;
    }
}

size_t HashTable::getSize() const 
{
    return size_;
}

double HashTable::load_factor() const 
{
    if (capacity_ == 0) {
        return 0.0;
    }
    return static_cast<double>(size_) / static_cast<double>(capacity_);
}

void HashTable::rehash() {
    size_t new_capacity = capacity_ * 2;

    auto* new_buckets = new std::forward_list<std::pair<std::string, int>>[new_capacity];

    // Move all elements to new buckets
    for (size_t i = 0; i < capacity_; ++i) 
    {
        for (auto& kv : buckets_[i]) 
        {
            size_t idx = std::hash<std::string>{}(kv.first) % new_capacity;
            new_buckets[idx].push_front(std::move(kv));
        }
    }

    // Delete old buckets
    delete[] buckets_;
    buckets_ = new_buckets;
    capacity_ = new_capacity;
}