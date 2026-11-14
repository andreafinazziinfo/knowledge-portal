"""User Management Service"""
from app.models.user import User

class UserService:
    def __init__(self):
        self.users = {}

    def register_user(self, user_id: str, email: str, name: str) -> User:
        user = User(user_id, email, name)
        self.users[user_id] = user
        return user

    def get_user(self, user_id: str) -> User:
        return self.users.get(user_id)
