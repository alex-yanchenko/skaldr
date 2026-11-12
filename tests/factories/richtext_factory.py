from skaldr.richtext import Rich, VisibleText, write_runs


def visible_text(runs: Rich) -> str:
    return write_runs(runs, VisibleText())
