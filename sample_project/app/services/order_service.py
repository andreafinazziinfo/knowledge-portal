"""Order Processing Service"""
from app.models.order import Order
from app.services.user_service import UserService

class OrderService:
    def __init__(self, user_service: UserService):
        self.user_service = user_service
        self.orders = {}

    def create_order(self, order_id: str, user_id: str, amount: float) -> Order:
        user = self.user_service.get_user(user_id)
        if not user:
            raise ValueError(f"User {user_id} not found")
        order = Order(order_id, user_id, amount)
        self.orders[order_id] = order
        return order
