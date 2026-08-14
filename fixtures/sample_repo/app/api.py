from app.service import Greeter


def handle_request(name: str) -> str:
    greeter = Greeter()
    return greeter.greet(name)

