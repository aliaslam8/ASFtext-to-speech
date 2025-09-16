class KeyManager:
    def __init__(self, limit=50000):
        """
        Manage multiple Speechify API keys with usage tracking.
        """
        self.keys = []   # [{"key": "...", "used": int}]
        self.limit = limit

    def load_keys(self, keys):
        """Load keys fresh"""
        self.keys = [{"key": k.strip(), "used": 0} for k in keys if k and k.strip()]
        print(f"✅ Loaded {len(self.keys)} keys")

    def add_key(self, key):
        """Add a new key"""
        if key and key.strip():
            self.keys.append({"key": key.strip(), "used": 0})
            print(f"➕ Added key {key[:8]}..., total = {len(self.keys)}")

    def get_available_key(self, chars_needed):
        """
        Return the first available key that can handle this request.
        """
        for api in self.keys:
            if api["used"] + chars_needed <= self.limit:
                api["used"] += chars_needed
                return api["key"]
        return None

    def deactivate_key(self, bad_key: str):
        """Remove a specific key from the pool"""
        for i, api in enumerate(self.keys):
            if api["key"] == bad_key:
                removed = self.keys.pop(i)
                print(f"❌ Deactivated key {removed['key'][:8]}..., {len(self.keys)} left")
                return removed
        return None

    def delete_first_key(self):
        """Remove the first key (legacy method)"""
        if self.keys:
            removed = self.keys.pop(0)
            print(f"❌ Deleted key {removed['key'][:8]}..., {len(self.keys)} left")
            return removed
        return None

    def active_keys_left(self):
        """Are there any usable keys left?"""
        return any(api["used"] < self.limit for api in self.keys)

    def count(self):
        return len(self.keys)