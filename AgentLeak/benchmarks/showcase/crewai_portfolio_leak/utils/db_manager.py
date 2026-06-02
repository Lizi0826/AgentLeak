import json
from pathlib import Path
from typing import Dict, Optional

class DBManager:
    def __init__(self, db_path: str = "data/vault.json"):
        self.db_path = Path(__file__).parent.parent / db_path
        self._ensure_db()

    def _ensure_db(self):
        if not self.db_path.exists():
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.db_path, 'w', encoding="utf-8") as f:
                json.dump({"users": []}, f, indent=2, ensure_ascii=False)

    def get_user(self, user_id: str) -> Optional[Dict]:
        with open(self.db_path, 'r', encoding="utf-8") as f:
            data = json.load(f)
            for user in data.get("users", []):
                if user["id"] == user_id:
                    return user
        return None

    def get_all_users(self):
        with open(self.db_path, 'r', encoding="utf-8") as f:
            data = json.load(f)
            return data.get("users", [])
