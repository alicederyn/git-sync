from subprocess import check_call, check_output


def get_current_branch() -> bytes:
    return check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"]).strip()


def get_main_upstream() -> bytes:
    return check_output(["git", "rev-parse", "--abbrev-ref", "main@{u}"]).strip()


def main() -> None:
    current_branch = get_current_branch()
    if current_branch == b"main":
        check_call(["git", "pull", "--all"])
    else:
        check_call(["git", "fetch", "--all"])
        main_upstream = get_main_upstream()
        check_call(["git", "fetch", ".", main_upstream + b":main"])
    check_call(["git", "push", "origin", "main"])
