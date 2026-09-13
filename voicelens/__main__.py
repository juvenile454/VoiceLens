"""Desktop entrypoint plus local diagnostics; never starts recording implicitly."""
import argparse
import json
import sys

from .i18n import set_language, t
from .settings import DEFAULT_MODEL, KNOWN_MODELS, normalize_language, normalize_model


def main():
    parser = argparse.ArgumentParser(description=t('cli_description'))
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--transcribe', metavar='FILE', help=t('cli_transcribe'))
    group.add_argument('--list-microphones', action='store_true', help=t('cli_list_mics'))
    group.add_argument('--check', action='store_true', help=t('cli_check'))
    parser.add_argument('--model', default=DEFAULT_MODEL, choices=sorted(KNOWN_MODELS), help=t('cli_model'))
    parser.add_argument('--language', default='en', choices=('en', 'de'), help=t('cli_language'))
    args = parser.parse_args()
    set_language(normalize_language(args.language))
    if args.check:
        from .diagnostics import inspect_setup
        report = inspect_setup()
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report['ready'] else 1
    if args.transcribe or args.list_microphones:
        from . import backend
        try:
            if args.transcribe:
                result = backend.transcribe_file(
                    args.transcribe,
                    model=normalize_model(args.model),
                    language=normalize_language(args.language),
                )
            else:
                result = backend.list_microphones()
            print(json.dumps(result, ensure_ascii=False))
            return 0
        except (backend.AppError, OSError) as error:
            print(json.dumps({'error': str(error)}, ensure_ascii=False), file=sys.stderr)
            return 1
    from .ui import run
    return run()


if __name__ == '__main__':
    raise SystemExit(main())
