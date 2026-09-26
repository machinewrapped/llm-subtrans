"""Write licence notices for the third-party packages bundled in a PyInstaller build.

The finished bundle is inspected, so the notices cover what actually shipped.
Modules come from the executable's PYZ archive and from the top-level entries in its _internal directory.
Each module is mapped to its installed distribution, whose licence files are read from the build environment.
"""

import argparse
from importlib import metadata
from pathlib import Path
import sys
import tempfile

import regex
from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader  # type: ignore

APP_NAME = 'gui-subtrans'
PROJECT_DISTRIBUTION = 'llm-subtrans'
NOTICES_FILENAME = 'THIRD-PARTY-NOTICES.txt'
PYZ_TYPECODE = 'z'
EXTENSION_SUFFIXES = ('.pyd', '.so')
METADATA_SUFFIXES = ('.dist-info', '.egg-info')
LICENSE_FILE_PATTERN = regex.compile(r'^(licen[cs]e|copying|notice)', regex.IGNORECASE)
SEPARATOR = '=' * 78

# Bundle entries that are not third-party modules
IGNORED_MODULES = {'assets', 'instructions', 'locales', 'theme', 'GuiSubtrans', 'PySubtrans'}
IGNORED_MODULE_PREFIXES = ('pyimod', '_pyi_', 'pyi_')


def ListArchivedModules(executable : Path) -> set[str]:
    """Return the top-level module names in the executable's PYZ archive."""
    archive = CArchiveReader(str(executable))
    pyz_names = [name for name, entry in archive.toc.items() if entry[-1] == PYZ_TYPECODE]

    modules : set[str] = set()
    with tempfile.TemporaryDirectory() as temp_dir:
        for pyz_name in pyz_names:
            pyz_path = Path(temp_dir) / Path(pyz_name).name
            pyz_path.write_bytes(archive.extract(pyz_name))

            reader = ZlibArchiveReader(str(pyz_path))
            modules.update(name.split('.')[0] for name in reader.toc)

    return modules


def ListInternalModules(internal_directory : Path) -> set[str]:
    """Return the top-level package and extension module names in the _internal directory."""
    modules : set[str] = set()
    for entry in internal_directory.iterdir():
        if entry.is_dir():
            name = entry.name
        elif entry.suffix in EXTENSION_SUFFIXES:
            name = entry.name.split('.')[0]
        else:
            continue

        # Skips metadata and native library folders such as numpy.libs
        if name.isidentifier():
            modules.add(name)

    return modules


def CanonicalName(name : str) -> str:
    """Normalise a distribution name so that spelling variants compare equal."""
    return regex.sub(r'[-_.]+', '-', name).lower()


def FindDistributions(modules : set[str]) -> tuple[dict[str, metadata.Distribution], list[str]]:
    """
    Map bundled modules to the distributions that installed them.
    Returns the distributions by canonical name, and the modules that no distribution claims.
    """
    module_owners = metadata.packages_distributions()
    distributions : dict[str, metadata.Distribution] = {}
    unresolved : list[str] = []

    for module in sorted(modules):
        if module in IGNORED_MODULES or module.startswith(IGNORED_MODULE_PREFIXES):
            continue

        owners = module_owners.get(module)
        if not owners:
            if module not in sys.stdlib_module_names:
                unresolved.append(module)
            continue

        for owner in owners:
            distribution = metadata.distribution(owner)
            name = CanonicalName(distribution.metadata['Name'])
            if name != PROJECT_DISTRIBUTION:
                distributions[name] = distribution

    return distributions, unresolved


def ReadLicenseFiles(distribution : metadata.Distribution) -> list[tuple[str, str]]:
    """Return (filename, text) for each licence or notice file in the distribution's metadata."""
    license_files : list[tuple[str, str]] = []
    seen_texts : set[str] = set()

    for file in distribution.files or []:
        parts = file.parts
        if len(parts) < 2 or not parts[0].endswith(METADATA_SUFFIXES):
            continue

        # PEP 639 puts every licence file under licenses/, including third-party ones
        in_licenses_folder = len(parts) > 2 and parts[1] == 'licenses'
        if not (in_licenses_folder or LICENSE_FILE_PATTERN.match(file.name)):
            continue

        path = Path(str(distribution.locate_file(file)))
        if not path.is_file():
            continue

        text = path.read_text(encoding='utf-8', errors='replace').strip()
        if text and text not in seen_texts:
            seen_texts.add(text)
            license_files.append(('/'.join(parts[1:]), text))

    return license_files


def DescribeLicense(distribution : metadata.Distribution) -> tuple[str, str]:
    """
    Summarise the licence declared in the distribution's metadata.
    Returns a short licence name, and the full licence text when the metadata embeds one.
    """
    fields = distribution.metadata.json
    expression = fields.get('license_expression')
    if isinstance(expression, str) and expression:
        return expression, ""

    license_field = fields.get('license')
    if isinstance(license_field, str) and license_field.strip():
        # Some packages put the whole licence text in the License field
        if '\n' in license_field.strip():
            return "", license_field.strip()
        return license_field.strip(), ""

    classifiers = fields.get('classifier', [])
    if isinstance(classifiers, str):
        classifiers = [classifiers]
    licenses = [classifier.split('::')[-1].strip() for classifier in classifiers if classifier.startswith('License ::')]
    return ', '.join(licenses), ""


def FindHomepage(distribution : metadata.Distribution) -> str:
    """Return the project's homepage or source URL from its metadata, if it declares one."""
    fields = distribution.metadata.json
    homepage = fields.get('home_page')
    if isinstance(homepage, str) and homepage:
        return homepage

    project_urls = fields.get('project_url', [])
    if isinstance(project_urls, str):
        project_urls = [project_urls]

    for entry in project_urls:
        label, _separator, url = entry.partition(',')
        if label.strip().lower() in ('homepage', 'home', 'source', 'repository', 'source code'):
            return url.strip()

    return project_urls[0].partition(',')[2].strip() if project_urls else ""


def BuildNotices(distributions : dict[str, metadata.Distribution]) -> tuple[str, list[str]]:
    """Return the notices text, and the names of packages with no licence text to include."""
    sections : list[str] = [
        "Third-party notices for GUI-Subtrans",
        "",
        "GUI-Subtrans includes the following third-party packages.",
        "Each package's licence terms are reproduced below.",
    ]
    missing : list[str] = []

    for name in sorted(distributions):
        distribution = distributions[name]
        license_name, embedded_text = DescribeLicense(distribution)
        license_files = ReadLicenseFiles(distribution)

        sections.append("")
        sections.append(SEPARATOR)
        sections.append(f"{distribution.metadata['Name']} {distribution.version}")
        if license_name:
            sections.append(f"License: {license_name}")

        homepage = FindHomepage(distribution)
        if homepage:
            sections.append(f"Homepage: {homepage}")

        for filename, text in license_files:
            sections.append("")
            sections.append(f"--- {filename} ---")
            sections.append(text)

        if not license_files and embedded_text:
            sections.append("")
            sections.append(embedded_text)

        if not license_files and not embedded_text:
            missing.append(f"{distribution.metadata['Name']} {distribution.version} ({license_name or 'unknown licence'})")

    return '\n'.join(sections) + '\n', missing


def main() -> int:
    parser = argparse.ArgumentParser(description="Write licence notices for the third-party packages in a PyInstaller build.")
    parser.add_argument('--dist-dir', default=f"dist/{APP_NAME}", help="The PyInstaller output directory for the application")
    parser.add_argument('--output', help=f"Where to write the notices (default: {NOTICES_FILENAME} in the _internal directory)")
    args = parser.parse_args()

    dist_directory = Path(args.dist_dir)
    internal_directory = dist_directory / '_internal'
    executable = dist_directory / (APP_NAME + ('.exe' if sys.platform == 'win32' else ''))

    if not executable.is_file() or not internal_directory.is_dir():
        print(f"ERROR: No PyInstaller build found in {dist_directory}")
        return 1

    modules = ListArchivedModules(executable) | ListInternalModules(internal_directory)
    distributions, unresolved = FindDistributions(modules)
    notices, missing = BuildNotices(distributions)

    output_path = Path(args.output) if args.output else internal_directory / NOTICES_FILENAME
    output_path.write_text(notices, encoding='utf-8')
    print(f"Wrote notices for {len(distributions)} packages to {output_path}")

    for entry in missing:
        print(f"WARNING: No licence text found for {entry}")

    if unresolved:
        print(f"WARNING: No installed package claims these bundled modules: {', '.join(unresolved)}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
