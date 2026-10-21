
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import quote
import hashlib
import json
import os
import re
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "documents" / "data" / "documents.json"

HASH_CHUNK_SIZE = 1024 * 1024
PROGRESS_EVERY = 100
TEMP_PREFIX = "auf2026-catalog-"

SOURCE_REPOSITORIES = [
    {
        "name": "FAURE-FOUNDATION",
        "url": "https://github.com/AUF2026/FAURE-FOUNDATION.git",
        "branch": "main",
    },
    {
        "name": "AUF2026.github.io",
        "url": "https://github.com/AUF2026/AUF2026.github.io.git",
        "branch": "main",
    },
]

CATEGORIES = {
    "certifications": ("Certificazioni", "CERTIFICATION"),
    "refutations": ("Confutazioni", "REFUTATION"),
    "validations": ("Validazioni", "VALIDATION"),
    "manuscripts": ("Manoscritti", "MANUSCRIPT"),
    "theorems": ("Teoremi", "THEOREM"),
    "proofs": ("Dimostrazioni", "PROOF"),
    "data": ("Dati e verifiche", "DATA"),
    "protocols": ("Protocolli", "PROTOCOL"),
    "bibliography": ("Bibliografia", "BIBLIOGRAPHY"),
    "datasets": ("Dataset", "DATASET"),
    "code": ("Codice sorgente", "CODE"),
    "docs": ("Documentazione", "DOCUMENTATION"),
    "pages": ("Pagine web", "PAGE"),
}

CATEGORY_ALIASES = {
    "certification": "certifications",
    "certifications": "certifications",
    "certificazioni": "certifications",
    "refutation": "refutations",
    "refutations": "refutations",
    "confutazioni": "refutations",
    "validation": "validations",
    "validations": "validations",
    "validazioni": "validations",
    "manuscript": "manuscripts",
    "manuscripts": "manuscripts",
    "manoscritti": "manuscripts",
    "theorem": "theorems",
    "theorems": "theorems",
    "teoremi": "theorems",
    "proof": "proofs",
    "proofs": "proofs",
    "dimostrazioni": "proofs",
    "data": "data",
    "datasets": "datasets",
    "dataset": "datasets",
    "protocol": "protocols",
    "protocols": "protocols",
    "protocolli": "protocols",
    "bibliography": "bibliography",
    "bibliografia": "bibliography",
    "code": "code",
    "src": "code",
    "docs": "docs",
    "documentation": "docs",
    "documentazione": "docs",
    "pages": "pages",
    "pagine": "pages",
}

EXCLUDED_DIRS = {
    ".git",
    ".github",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".next",
    ".nuxt",
    "dist",
    "build",
    "coverage",
    ".idea",
    ".vscode",
}

EXCLUDED_FILES = {
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    "README.md",
    "LICENSE",
    "LICENSE.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
}

# File di servizio esclusi quando si trovano alla radice.
ROOT_SERVICE_FILES = {
    "index.html",
    "404.html",
    "archive.html",
    "build.py",
    "catalog.yml",
    "catalog.yaml",
}

METADATA_SUFFIX = ".json"


def readable_title(filename):
    title = Path(filename).stem
    title = re.sub(r"[_-]+", " ", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title[:1].upper() + title[1:] if title else filename


def sha256_file(path):
    digest = hashlib.sha256()

    with path.open("rb") as stream:
        for chunk in iter(
            lambda: stream.read(HASH_CHUNK_SIZE), b""
        ):
            digest.update(chunk)

    return digest.hexdigest()


def is_excluded(path):
    """Esclude file tecnici e temporanei, mai in base all'estensione."""

    if path.name in EXCLUDED_FILES:
        return True

    if any(
        part.casefold() in EXCLUDED_DIRS
        for part in path.parts
    ):
        return True

    if path.is_symlink():
        return True

    if (
        path.name == "documents.json"
        and "data" in {
            part.casefold() for part in path.parts
        }
    ):
        return True

    if (
        path.name.startswith(".documents-")
        and path.suffix.lower() == ".tmp"
    ):
        return True

    # IMPORTANTE:
    # non filtrare per estensione.
    # PDF, DOCX, XLSX, immagini, archivi, binari,
    # nuovi formati e file senza estensione sono ammessi.

    return False


def is_metadata_sidecar(path):
    """
    Un JSON con lo stesso nome di un altro file viene considerato
    metadato associato e non una voce documentale separata.
    Gli altri JSON vengono indicizzati normalmente.
    """

    if path.suffix.lower() != METADATA_SUFFIX:
        return False

    try:
        for sibling in path.parent.iterdir():
            if sibling == path or not sibling.is_file():
                continue

            if sibling.is_symlink():
                continue

            if sibling.stem.casefold() != path.stem.casefold():
                continue

            if sibling.suffix.lower() != METADATA_SUFFIX:
                return True

    except OSError as exc:
        print(f"[WARN] Impossibile controllare {path}: {exc}")

    return False


def load_metadata(document):
    metadata_path = document.with_suffix(METADATA_SUFFIX)

    if not metadata_path.is_file():
        return {}

    try:
        with metadata_path.open("r", encoding="utf-8") as stream:
            value = json.load(stream)

        if isinstance(value, dict):
            return value

        print(f"[WARN] Metadati non validi: {metadata_path}")

    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
    ) as exc:
        print(f"[WARN] Metadati ignorati: {metadata_path}: {exc}")

    return {}


def classify_document(relative_path):
    path = Path(relative_path)
    parts = [part.casefold() for part in path.parts[:-1]]

    # La cartella di categoria più specifica prevale.
    for part in reversed(parts):
        category = CATEGORY_ALIASES.get(part)
        if category:
            return category

    # Categoria predefinita per qualsiasi altra estensione.
    extension = path.suffix.lower()

    extension_categories = {
        ".html": "pages",
        ".htm": "pages",
        ".tex": "manuscripts",
        ".bib": "bibliography",
        ".csv": "datasets",
        ".tsv": "datasets",
        ".xlsx": "datasets",
        ".xls": "datasets",
        ".ods": "datasets",
        ".ipynb": "code",
        ".py": "code",
        ".js": "code",
        ".ts": "code",
        ".css": "code",
        ".lean": "proofs",
        ".thy": "proofs",
        ".v": "proofs",
    }

    return extension_categories.get(extension, "docs")


def is_in_document_area(relative_path):
    """
    Limita la scansione alle aree documentali previste.
    Non limita le estensioni dei file.
    """

    path = Path(relative_path)
    parts = path.parts

    if not parts:
        return False

    lowered = [part.casefold() for part in parts]

    # File alla radice: esclude soltanto quelli di servizio
    # esplicitamente identificati.
    if len(parts) == 1:
        return parts[0].casefold() not in {
            name.casefold() for name in ROOT_SERVICE_FILES
        }

    # Aree documentali standard di entrambe le repository.
    if lowered[0] in {"docs", "documents"}:
        return True

    # Cartelle di categoria riconosciute anche alla radice.
    if any(
        part in CATEGORY_ALIASES
        for part in lowered[:-1]
    ):
        return True

    return False


def collect_files(repository_root):
    files = []

    for current_root, dirs, filenames in os.walk(
        repository_root,
        topdown=True,
        followlinks=False,
    ):
        current = Path(current_root)

        dirs[:] = sorted(
            [
                name
                for name in dirs
                if name.casefold() not in EXCLUDED_DIRS
                and not (current / name).is_symlink()
            ],
            key=str.casefold,
        )

        for filename in filenames:
            path = current / filename

            if not path.is_file() or is_excluded(path):
                continue

            relative = path.relative_to(
                repository_root
            ).as_posix()

            if not is_in_document_area(relative):
                continue

            if is_metadata_sidecar(path):
                continue

            files.append(path)

    return sorted(
        files,
        key=lambda path: path.as_posix().casefold(),
    )


def build_document(repository, repository_root, path):
    relative_path = path.relative_to(
        repository_root
    ).as_posix()

    category = classify_document(relative_path)
    label, document_type = CATEGORIES[category]
    metadata = load_metadata(path)
    stat = path.stat()

    identity = hashlib.sha256(
        f"{repository['name']}/{relative_path}".encode("utf-8")
    ).hexdigest()[:20]

    repository_url = repository["url"].removesuffix(".git")
    encoded_path = quote(relative_path, safe="/")
    branch = quote(repository["branch"], safe="")

    source_url = (
        f"{repository_url}/blob/{branch}/{encoded_path}"
    )

    download_url = (
        f"https://raw.githubusercontent.com/"
        f"AUF2026/{quote(repository['name'], safe='')}/"
        f"{branch}/{encoded_path}"
    )

    title = metadata.get("title")

    if not isinstance(title, str) or not title.strip():
        title = readable_title(path.name)

    external_links = metadata.get("externalLinks", [])

    if not isinstance(external_links, list):
        external_links = []

    return {
        "id": f"{category}-{identity}",
        "title": title.strip(),
        "category": category,
        "categoryLabel": label,
        "type": document_type,
        "file": relative_path,
        "filename": path.name,
        "extension": path.suffix.lower().lstrip("."),
        "sizeBytes": stat.st_size,
        "sha256": sha256_file(path),
        "repository": repository["name"],
        "repositoryUrl": repository_url,
        "sourceUrl": source_url,
        "downloadUrl": download_url,
        "verification": {
            "status": metadata.get(
                "verificationStatus", "NOT_RECORDED"
            ),
            "report": metadata.get("verificationReport"),
            "verifier": metadata.get("verifier"),
            "verifiedAt": metadata.get("verifiedAt"),
            "method": metadata.get("verificationMethod"),
        },
        "identifiers": {
            "doi": metadata.get("doi"),
            "orcid": metadata.get("orcid"),
            "hal": metadata.get("hal"),
        },
        "externalLinks": external_links,
    }


def write_catalog(repository_roots):
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    documents = []

    for repository, repository_root, files in repository_roots:
        for path in files:
            try:
                document = build_document(
                    repository,
                    repository_root,
                    path,
                )
                documents.append(document)

            except OSError as exc:
                # Un file illeggibile non interrompe l'intero catalogo.
                print(f"[WARN] File ignorato {path}: {exc}")
                continue

            if len(documents) % PROGRESS_EVERY == 0:
                print(f"[PROGRESS] {len(documents)} documenti")

    documents.sort(
        key=lambda item: (
            item["categoryLabel"].casefold(),
            item["title"].casefold(),
            item["repository"].casefold(),
            item["file"].casefold(),
        )
    )

    counts = {category: 0 for category in CATEGORIES}

    for document in documents:
        counts[document["category"]] += 1

    catalog = {
        "institution": "FAURE FOUNDATION",
        "catalogTitle": "Official Scientific Register",
        "schemaVersion": 3,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "count": len(documents),
        "categoryCounts": counts,
        "categories": [
            {
                "id": category,
                "label": label,
                "type": document_type,
                "count": counts[category],
            }
            for category, (label, document_type)
            in CATEGORIES.items()
        ],
        "sources": [
            {
                "name": repository["name"],
                "url": repository["url"].removesuffix(".git"),
                "branch": repository["branch"],
            }
            for repository, _, _ in repository_roots
        ],
        "documents": documents,
    }

    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=OUTPUT.parent,
            prefix=".documents-",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temp_path = Path(stream.name)

            json.dump(
                catalog,
                stream,
                ensure_ascii=False,
                indent=2,
            )

            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())

        # Verifica il JSON prima di sostituire il catalogo esistente.
        with temp_path.open("r", encoding="utf-8") as stream:
            checked = json.load(stream)

        if checked["count"] != len(checked["documents"]):
            raise RuntimeError(
                "Conteggio catalogo non coerente."
            )

        os.replace(temp_path, OUTPUT)
        temp_path = None

    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    print("[INFO] Documenti per categoria:")

    for category, count in counts.items():
        print(f"  {CATEGORIES[category][0]}: {count}")

    print(f"[INFO] Totale documenti: {len(documents)}")

    return len(documents)


def clone_repository(repository, destination):
    print(f"[CLONE] {repository['name']}")

    command = [
        "git",
        "clone",
        "--depth", "1",
        "--single-branch",
        "--branch", repository["branch"],
        repository["url"],
        str(destination),
    ]

    subprocess.run(
        command,
        check=True,
        timeout=600,
    )


def main():
    print("[START] Catalogo scientifico AUF2026")

    with tempfile.TemporaryDirectory(
        prefix=TEMP_PREFIX
    ) as temp_dir:
        temp_root = Path(temp_dir)
        repository_roots = []

        for index, repository in enumerate(SOURCE_REPOSITORIES):
            clone_path = temp_root / f"source-{index}"

            try:
                clone_repository(repository, clone_path)

            except (
                OSError,
                subprocess.SubprocessError,
            ) as exc:
                raise RuntimeError(
                    f"Impossibile recuperare {repository['name']}. "
                    f"Catalogo precedente preservato: {exc}"
                ) from exc

            files = collect_files(clone_path)

            print(
                f"[SCAN] {repository['name']}: "
                f"{len(files)} file documentali"
            )

            repository_roots.append(
                (repository, clone_path, files)
            )

        count = write_catalog(repository_roots)

    print(f"[OK] Catalogo aggiornato: {count} documenti")
    print(f"[OK] Output: {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    try:
        main()

    except (
        OSError,
        ValueError,
        TypeError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as exc:
        raise SystemExit(f"[ERRORE] {exc}") from exc
