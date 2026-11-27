import sys


def _main():
    if "--worker" in sys.argv:
        from asenamask.worker import main as worker_main
        return worker_main(sys.argv[sys.argv.index("--worker") + 1])
    if "--server" in sys.argv:
        from asenamask.server import main as server_main
        return server_main(sys.argv[sys.argv.index("--server") + 1])
    if "--probe" in sys.argv:
        from asenamask.server import probe
        return probe(sys.argv[sys.argv.index("--probe") + 1:])
    if "--selftest" in sys.argv:
        from asenamask.common import selftest
        return selftest()
    from asenamask.ui.app import run
    return run()


if __name__ == "__main__":
    sys.exit(_main())
