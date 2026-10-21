
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "documents"
OUTPUT = DOCS / "data" / "documents.json"

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
    "certifications": ("CERTIFICAZIONI", "CERTIFICATION"),
    "refutations": ("CONFUTAZIONI", "REFUTATION"),
    "validations": ("VALIDAZIONI", "VALIDATION"),
    "manuscripts": ("MANOSCRITTI", "MANUSCRIPT"),
    "theorems": ("TEOREMI", "THEOREM"),
    "proofs": ("DIMOSTRAZIONI", "PROOF"),
    "data": ("DATI E VERIFICHE", "DATA"),
    "protocols": ("PROTOCOLLI", "PROTOCOL"),
    "bibliography": ("BIBLIOGRAFIA", "BIBLIOGRAPHY"),
    "datasets": ("DATASET", "DATASET"),
    "code": ("CODICE SORGENTE", "CODE"),
    "docs": ("DOCUMENTAZIONE", "DOCUMENTATION"),
    "pages": ("PAGINE", "PAGE"),
}

EXCLUDED_DIRS = {
    ".git", ".github", "__pycache__", "node_modules",
    ".venv", "venv", ".next", ".nuxt", "dist",
    "build", "coverage", ".idea", ".vscode",
}

EXCLUDED_FILES = {
    ".DS_Store", "Thumbs.db", "desktop.ini",
}

ALLOWED_EXTENSIONS = {
    ".pdf", ".md", ".markdown", ".txt", ".rst",
    ".html", ".htm", ".tex", ".bib", ".rtf",
    ".doc", ".docx", ".odt",
    ".json", ".jsonld", ".xml", ".yaml", ".yml",
    ".csv", ".tsv", ".xlsx", ".xls", ".ods",
    ".ipynb", ".py", ".pyi", ".r", ".jl",
    ".lean", ".thy", ".v", ".vhd", ".sv",
    ".c", ".h", ".cpp", ".hpp", ".rs", ".go",
    ".java", ".js", ".jsx", ".ts", ".tsx",
    ".css", ".scss", ".sh", ".bash", ".sql",
    ".toml", ".ini", ".cfg", ".conf",
    ".log", ".diff", ".patch", ".proto",
    ".graphql", ".gql", ".m", ".mm",
}

EXTENSION_CATEGORY = {
    ".pdf": "docs",
    ".md": "docs",
    ".markdown": "docs",
    ".rst": "docs",
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
    ".pyi": "code",
    ".r": "code",
    ".jl": "code",
    ".lean": "proofs",
    ".thy": "proofs",
    ".v": "proofs",
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
        while True:
            chunk = stream.read(HASH_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)

    return digest.hexdigest()


def is_excluded(path):
    if path.name in EXCLUDED_FILES:
        return True

    if any(part.casefold() in EXCLUDED_DIRS for part in path.parts):
        return True

    if path.is_symlink():
        return True

    # Non indicizzare il catalogo generato.
    if (
        path.name == "documents.json"
        and "data" in path.parts
    ):
        return True

    # Non indicizzare file temporanei del catalogo.
    if path.name.startswith(".documents-") and path.suffix == ".tmp":
        return True

    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        return True

    return False


def is_metadata_sidecar(path):
    """Esclude un JSON se accanto esiste un documento con lo stesso nome."""
    if path.suffix.lower() != METADATA_SUFFIX:
        return False

    try:
        for sibling in path.parent.iterdir():
            if sibling == path or not sibling.is_file():
                continue

            if sibling.stem.casefold() != path.stem.casefold():
                continue

            if sibling.suffix.lower() != METADATA_SUFFIX:
                return True

    except OSError as exc:
        print(f"[WARN] Metadati non controllabili: {path}: {exc}")

    return False


def load_metadata(document):
    metadata_path = document.with_suffix(METADATA_SUFFIX)

    if not metadata_path.is_file():
        return {}

    try:
        with metadata_path.open("r", encoding="utf-8") as stream:
            metadata = json.load(stream)

        if isinstance(metadata, dict):
            return metadata

        print(f"[WARN] Metadati non oggetto JSON: {metadata_path}")

    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"[WARN] Metadati ignorati: {metadata_path}: {exc}")

    return {}


def classify_document(relative_path):
    parts = Path(relative_path).parts
    extension = Path(relative_path).suffix.lower()

    # La categoria indicata nel percorso ha la precedenza.
    for part in parts[:-1]:
        key = part.casefold()

        if key in CATEGORIES:
            return key

    return EXTENSION_CATEGORY.get(extension, "docs")


def collect_files(repository_root):
    """Scansiona tutta la repository senza caricare i contenuti in memoria."""
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

            if is_metadata_sidecar(path):
                continue

            files.append(path)

    files.sort(
        key=lambda path: path.as_posix().casefold()
    )

    return files


def build_document(repository, repository_root, path):
    relative_path = path.relative_to(repository_root).as_posix()
    category = classify_document(relative_path)
    label, document_type = CATEGORIES[category]

    metadata = load_metadata(path)
    stat = path.stat()

    identity_input = (
        repository["name"] + "/" + relative_path
    )

    identity = hashlib.sha256(
        identity_input.encode("utf-8")
    ).hexdigest()[:20]

    encoded_path = relative_path

    # Codifica i caratteri speciali per gli URL GitHub.
    from urllib.parse import quote
    encoded_path = quote(encoded_path, safe="/")

    repository_url = repository["url"].removesuffix(".git")

    return {
        "id": f"{category}-{identity}",
        "title": metadata.get(
            "title", readable_title(path.name)
        ),
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
        "sourceUrl": (
            f"{repository_url}/blob/"
            f"{repository['branch']}/{encoded_path}"
        ),
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
        "externalLinks": (
            metadata.get("externalLinks", [])
            if isinstance(metadata.get("externalLinks", []), list)
            else []
        ),
    }


def write_catalog(repository_roots):
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    total_candidates = sum(
        len(files)
        for _, _, files in repository_roots
    )

    processed = 0
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

            stream.write("{\n")
            stream.write('  "institution": "FAURE FOUNDATION",\n')
            stream.write(
                '  "catalogTitle": "Official Scientific Register",\n'
            )
            stream.write(
                '  "generatedAt": '
                + json.dumps(
                    datetime.now(timezone.utc).isoformat()
                )
                + ",\n"
            )

            # Il conteggio viene scritto dopo aver raccolto i documenti.
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
                        processed += 1

                        if processed % PROGRESS_EVERY == 0:
                            print(
                                f"[PROGRESS] "
                                f"{processed}/{total_candidates}"
                            )

                    except (OSError, ValueError, TypeError) as exc:
                        # Un errore di lettura non deve produrre
                        # silenziosamente un catalogo incompleto.
                        raise RuntimeError(
                            f"Impossibile indicizzare {path}: {exc}"
                        ) from exc

            stream.write(f'  "count": {len(documents)},\n')
            stream.write(
                '  "categories": '
                + json.dumps(
                    list(CATEGORIES),
                    ensure_ascii=False,
                )
                + ",\n"
            )
            stream.write(
                '  "sources": '
                + json.dumps(
                    [
                        repo["name"]
                        for repo, _, _ in repository_roots
                    ],
                    ensure_ascii=False,
                )
                + ",\n"
            )
            stream.write('  "documents": [\n')

            for index, document in enumerate(documents):
                if index:
                    stream.write(",\n")

                stream.write(
                    "    "
                    + json.dumps(
                        document,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )

            stream.write("\n  ]\n")
            stream.write("}\n")
            stream.flush()
            os.fsync(stream.fileno())

        # Controlla che il JSON sia valido prima di pubblicarlo.
        with temp_path.open("r", encoding="utf-8") as stream:
            json.load(stream)

        # Sostituzione atomica: il vecchio catalogo rimane disponibile
        # fino al completamento della nuova versione.
        os.replace(temp_path, OUTPUT)
        temp_path = None

    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass

    return processed


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
        stdout=subprocess.DEVNULL,
        stderr=None,
        timeout=600,
    )


def main():
    print("[START] Catalogo aggregato AUF2026")
    print(
        f"[INFO] Repository sorgente: "
        f"{len(SOURCE_REPOSITORIES)}"
    )

    with tempfile.TemporaryDirectory(
        prefix=TEMP_PREFIX
    ) as temp_dir:
        temp_root = Path(temp_dir)
        repository_roots = []

        for index, repository in enumerate(SOURCE_REPOSITORIES):
            clone_path = temp_root / f"source-{index}"

            try:
                clone_repository(repository, clone_path)

            except (OSError, subprocess.SubprocessError) as exc:
                raise RuntimeError(
                    f"Impossibile recuperare la repository "
                    f"{repository['name']}. Il catalogo precedente "
                    f"è stato preservato. Dettagli: {exc}"
                ) from exc

            print(f"[SCAN] {repository['name']}")

            files = collect_files(clone_path)

            print(
                f"[INFO] {repository['name']}: "
                f"{len(files)} file candidati"
            )

            repository_roots.append(
                (repository, clone_path, files)
            )

        total = sum(
            len(files)
            for _, _, files in repository_roots
        )

        print(f"[INFO] Totale file candidati: {total}")
        print("[START] Generazione del JSON")

        count = write_catalog(repository_roots)

    print(f"[OK] File indicizzati: {count}")
    print(f"[OK] Catalogo: {OUTPUT.relative_to(ROOT)}")


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
