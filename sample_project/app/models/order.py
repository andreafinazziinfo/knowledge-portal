"""Order Entity Model"""
class Order:
    def __init__(self, order_id: str, user_id: str, amount: float):
        self.order_id = order_id
        self.user_id = user_id
        self.amount = amount
        self.status = "pending"

    def mark_completed(self):
        self.status = "completed"
