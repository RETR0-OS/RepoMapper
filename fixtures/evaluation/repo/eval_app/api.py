from eval_app.auth import authorize


def handle_request(user: str) -> str:
    if not authorize(user):
        return "forbidden"
    return "accepted"
