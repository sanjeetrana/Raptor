class MockStorage:
    def __init__(self):
        self.data = {}

    def set(self, key, value, ttl=None):
        self.data[key] = value
        return True

    def get(self, key):
        return self.data.get(key)

    def delete(self, key):
        if key in self.data:
            del self.data[key]
            return True
        return False

    def exists(self, key):
        return key in self.data

    def expire(self, key, ttl):
        return key in self.data

    def ttl(self, key):
        if key not in self.data:
            return None
        return -1

    def keys(self):
        return list(self.data.keys())

    def flush(self):
        self.data.clear()
        return True