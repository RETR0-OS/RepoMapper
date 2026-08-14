from eval_app.store import load_policy


def authorize(user: str) -> bool:
    return load_policy(user)
