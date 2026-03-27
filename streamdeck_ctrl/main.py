"""CLI entry point, argument parsing, signal handling."""

import argparse
import logging
import os
import sys

from streamdeck_ctrl import __version__
from streamdeck_ctrl.daemon import StreamDeckDaemon, dry_run


def daemonize():
    """Standard Unix double-fork to detach from terminal."""
    # First fork
    if os.fork() > 0:
        sys.exit(0)
    os.setsid()
    # Second fork
    if os.fork() > 0:
        sys.exit(0)
    # Redirect stdio to /dev/null
    sys.stdout.flush()
    sys.stderr.flush()
    with open(os.devnull, "rb", 0) as f:
        os.dup2(f.fileno(), sys.stdin.fileno())
    with open(os.devnull, "ab", 0) as f:
        os.dup2(f.fileno(), sys.stdout.fileno())
        os.dup2(f.fileno(), sys.stderr.fileno())
    # After daemonize, logging must go to syslog
    import logging.handlers
    syslog = logging.handlers.SysLogHandler(address="/dev/log")
    syslog.setFormatter(logging.Formatter("streamdeck-ctrl: %(message)s"))
    logging.getLogger().addHandler(syslog)


def setup_logging(level_name):
    """Configure logging to stderr."""
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main(args=None):
    """Parse CLI args and run the daemon."""
    parser = argparse.ArgumentParser(
        prog="streamdeck-ctrl",
        description="Headless, config-driven Stream Deck control daemon.",
    )
    parser.add_argument(
        "--daemon", action="store_true",
        help="Daemonize: fork to background, detach from terminal",
    )
    parser.add_argument(
        "--config", required=True, metavar="PATH",
        help="Path to JSON layout config file",
    )
    parser.add_argument(
        "--socket-path", metavar="PATH",
        help="Override Unix socket path from config",
    )
    parser.add_argument(
        "--brightness", type=int, metavar="INT",
        help="Override brightness (0-100) from config",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Validate config and print key layout, do not open deck",
    )
    parser.add_argument(
        "--simulate", action="store_true",
        help="Run full daemon with simulated deck (no hardware required)",
    )
    parser.add_argument(
        "--log-level", default="info",
        choices=["debug", "info", "warning", "error"],
        help="Logging level (default: info)",
    )
    parser.add_argument(
        "--version", action="version", version=f"streamdeck-ctrl {__version__}",
    )

    opts = parser.parse_args(args)

    setup_logging(opts.log_level)

    if opts.dry_run:
        try:
            dry_run(opts.config)
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)
        return

    if opts.daemon:
        daemonize()

    daemon = StreamDeckDaemon(
        config_path=opts.config,
        socket_path=opts.socket_path,
        brightness=opts.brightness,
        simulate=opts.simulate,
    )

    try:
        daemon.run()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logging.getLogger(__name__).exception("Fatal error")
        sys.exit(1)


if __name__ == "__main__":
    main()
