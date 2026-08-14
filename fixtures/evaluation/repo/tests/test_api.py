from eval_app.api import handle_request


def test_handle_request_rejects_guest() -> None:
    assert handle_request("guest") == "forbidden"
