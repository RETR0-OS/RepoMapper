from app.helpers import normalize_name


class Greeter:
    def greet(self, name: str) -> str:
        return format_greeting(normalize_name(name))


def format_greeting(name: str) -> str:
    return f"Hello, {name}!"

