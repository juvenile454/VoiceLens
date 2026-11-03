"""Offline checks of repository documentation; no network."""
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import voicelens

SKIP_DIRS = ('verification', 'docs/superpowers')
SCHEME = re.compile(r'^[a-zA-Z][a-zA-Z0-9+.-]*:')
FENCE = re.compile(r'^ {0,3}(```|~~~).*?^ {0,3}\1[^\n]*$', re.M | re.S)
INLINE_CODE = re.compile(r'(`+)(?!`).+?(?<!`)\1(?!`)', re.S)
MD_LINK = re.compile(r'\]\(\s*(<[^>]*>|[^)\s]*)(?:\s+(?:"[^"]*"|\'[^\']*\'))?\s*\)')
HTML_LINK = re.compile(r'<(?:img|a)\b[^>]*?\b(?:src|href)\s*=\s*(?:"([^"]*)"|\'([^\']*)\')', re.I)
HEADING = re.compile(r'^ {0,3}#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$', re.M)


def markdown_files():
    """All *.md files in the repo, skipping dot-directories, verification/ and docs/superpowers/."""
    found = []
    for path in sorted(ROOT.rglob('*.md')):
        rel = path.relative_to(ROOT)
        if any(part.startswith('.') for part in rel.parts):
            continue
        posix = rel.as_posix()
        if any(posix == d or posix.startswith(d + '/') for d in SKIP_DIRS):
            continue
        found.append(path)
    return found


def github_slug(heading):
    text = re.sub(r'[^\w \-]', '', heading.strip().lower())
    return text.replace(' ', '-')


def _prose(path):
    text = path.read_text(encoding='utf-8')
    text = FENCE.sub('', text)
    return INLINE_CODE.sub('', text)


def links(path):
    """Link and image targets of a markdown file, excluding code."""
    return link_targets(_prose(path))


def link_targets(text):
    """Targets of `](...)` (links, images, linked images) and HTML img/a."""
    found = []
    for m in MD_LINK.finditer(text):
        found.append(m.group(1).strip('<>'))
    for m in HTML_LINK.finditer(text):
        found.append(m.group(1) if m.group(1) is not None else m.group(2))
    return [t for t in found if t]


def anchors(path):
    text = FENCE.sub('', path.read_text(encoding='utf-8'))
    seen, result = {}, set()
    for m in HEADING.finditer(text):
        slug = github_slug(re.sub(r'[*_`]|\[([^\]]*)\]\([^)]*\)', r'\1', m.group(1)))
        n = seen.get(slug, 0)
        seen[slug] = n + 1
        result.add(slug if n == 0 else f'{slug}-{n}')
    return result


def _local_targets(path):
    for target in links(path):
        if SCHEME.match(target):
            continue
        base, _, fragment = target.partition('#')
        dest = path if not base else (path.parent / base.split('?')[0])
        yield target, dest, fragment


class DocsTests(unittest.TestCase):
    def test_link_targets_include_linked_images(self):
        text = '[![Tests](badge.svg)](LICENSE) [x](a.md#b "t") <img src="i.png">'
        self.assertEqual(link_targets(text), ['badge.svg', 'LICENSE', 'a.md#b', 'i.png'])

    def test_relative_links_resolve(self):
        bad = []
        for md in markdown_files():
            for target, dest, _ in _local_targets(md):
                if not dest.exists():
                    bad.append(f'{md.relative_to(ROOT)}: {target}')
        self.assertEqual(bad, [], 'broken relative links:\n' + '\n'.join(bad))

    def test_same_file_anchors_exist(self):
        bad = []
        for md in markdown_files():
            for target, dest, fragment in _local_targets(md):
                if not fragment or not dest.exists():
                    continue
                if dest.suffix != '.md':
                    continue
                if fragment.lower() not in anchors(dest):
                    bad.append(f'{md.relative_to(ROOT)}: {target}')
        self.assertEqual(bad, [], 'missing anchors:\n' + '\n'.join(bad))

    def test_release_status_matches_package_version(self):
        self.assertIn(f'VoiceLens {voicelens.__version__}', (ROOT / 'docs/release.md').read_text(encoding='utf-8'))
        self.assertTrue((ROOT / f'docs/releases/v{voicelens.__version__}.md').exists())

    def test_presentation_assets_stay_small(self):
        files = [p for d in ('assets/screenshots', 'assets/demo') for p in (ROOT / d).glob('*') if p.is_file()]
        for p in files:
            self.assertLessEqual(p.stat().st_size, 3 * 1024 * 1024, p)
        self.assertLessEqual(sum(p.stat().st_size for p in files), 6 * 1024 * 1024)
        social = ROOT / 'assets/social/social-preview.png'
        if social.exists():
            self.assertLess(social.stat().st_size, 1024 * 1024)

    def test_changelog_top_entry_matches_version(self):
        text = (ROOT / 'CHANGELOG.md').read_text(encoding='utf-8')
        versions = re.findall(r'^## \[(\d+\.\d+\.\d+)\]', text, re.M)
        self.assertEqual(versions[0], voicelens.__version__)


if __name__ == '__main__':
    unittest.main()
