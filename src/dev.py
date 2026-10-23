from watchfiles import run_process


def dev():
    run_process("src", target="src.main.main", target_type="function", debounce=300)


if __name__ == "__main__":
    dev()
