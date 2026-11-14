"""User Entity Model"""
class User:
    def __init__(self, user_id: str, email: str, name: str):
        self.user_id = user_id
        self.email = email
        self.name = name

    def to_dict(self):
        return {"user_id": self.user_id, "email": self.email, "name": self.name}
