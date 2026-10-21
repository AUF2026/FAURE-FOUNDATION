
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import tempfile

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "documents"
OUTPUT = DOCS / "data" / "documents.json"

HASH_CHUNK_SIZE = 1024 * 1024  # 1 MiB
PROGRESS_EVERY = 100

CATEGORIES = {
    "certifications": {
        "label": "CERTIFICAZIONI",
        "type": "CERTIFICATION",
    },
    "refutations": {
        "label": "CONFUTAZIONI",
        "type": "REFUTATION",
    },
    "validations": {
        "label": "VALIDAZIONI",
        "type": "VALIDATION",
    },
    "manuscripts": {
        "label": "MANOSCRITTI",
        "type": "MANUSCRIPT",
    },
    "theorems": {
        "label": "TEOREMI",
        "type": "THEOREM",
    },
    "proofs": {
        "label": "DIMOSTRAZIONI",
        "type": "PROOF",
    },
    "data": {
        "label": "DATI E VERIFICHE",
        "type": "DATA",
    },
    "protocols": {
        "label": "PROTOCOLLI",
        "type": "PROTOCOL",
    },
    "bibliography": {
        "label": "BIBLIOGRAFIA",
        "type": "BIBLIOGRAPHY",
    },
    "datasets": {
        "label": "DATASET",
        "type": "DATASET",
    },
    "code": {
        "label": "CODICE SORGENTE",
        "type": "CODE",
    },
    "docs": {
        "label": "DOCUMENTAZIONE",
        "type": "DOCUMENTATION",
    },
    "pages": {
        "label": "PAGINE",
        "type": "PAGE",
    },
}

EXCLUDED_DIRS = {
    ".git",
    ".github",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
}

EXCLUDED_FILES = {
    ".DS_Store",
    "Thumbs.db",
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


def load_metadata(document):
    metadata_path = document.with_suffix(METADATA_SUFFIX)

    if metadata_path == OUTPUT or not metadata_path.is_file():
        return {}

    try:
        with metadata_path.open("r", encoding="utf-8") as stream:
            metadata = json.load(stream)
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(
            f"Metadati non validi: {metadata_path.relative_to(ROOT)}"
        ) from exc

    if not isinstance(metadata, dict):
        raise ValueError(
            f"I metadati devono essere un oggetto JSON: "
            f"{metadata_path.relative_to(ROOT)}"
        )

    return metadata


def is_metadata_sidecar(path):
    """
    Un file JSON viene considerato metadato soltanto se esiste
    un altro file con lo stesso nome base nella stessa directory.

    Esempio:
        paper.pdf + paper.json -> paper.json è un sidecar.
        records.json senza records.pdf -> records.json è un documento.
    """
    if path.suffix.lower() != METADATA_SUFFIX:
        return False

    if path.resolve() == OUTPUT.resolve():
        return True

    try:
        for sibling in path.parent.iterdir():
            if sibling == path or not sibling.is_file():
                continue

            if sibling.stem.casefold() == path.stem.casefold():
                return True
    except OSError as exc:
        raise OSError(
            f"Impossibile esaminare {path.parent}"
        ) from exc

    return False


def is_excluded(path):
    if path.name in EXCLUDED_FILES:
        return True

    if any(part in EXCLUDED_DIRS for part in path.parts):
        return True

    try:
        if path.resolve() == OUTPUT.resolve():
            return True
    except OSError:
        return True

    if is_metadata_sidecar(path):
        return True

    return False


def collect_files():
    """
    Conserva in memoria soltanto i percorsi, non il contenuto
    dei documenti. La lista viene ordinata in modo deterministico.
    """
    files = []

    for folder in CATEGORIES:
        directory = DOCS / folder

        if not directory.is_dir():
            print(f"[INFO] Categoria assente: {folder}")
            continue

        for path in directory.rglob("*"):
            if not path.is_file():
                continue

            if is_excluded(path):
                continue

            files.append((folder, path))

    files.sort(
        key=lambda item: (
            CATEGORIES[item[0]]["label"].casefold(),
            item[1].relative_to(ROOT).as_posix().casefold(),
        )
    )

    return files


def build_document(folder, path):
    config = CATEGORIES[folder]
    relative_path = path.relative_to(ROOT).as_posix()
    metadata = load_metadata(path)
    stat = path.stat()

    # L'ID dipende dal percorso relativo, quindi file omonimi
    # in sottocartelle diverse non collidono.
    identity = hashlib.sha256(
        relative_path.encode("utf-8")
    ).hexdigest()[:16]

    return {
        "id": f"{folder}-{identity}",
        "title": metadata.get("title", readable_title(path.name)),
        "category": folder,
        "categoryLabel": config["label"],
        "type": config["type"],
        "file": relative_path,
        "filename": path.name,
        "extension": path.suffix.lower().lstrip("."),
        "sizeBytes": stat.st_size,
        "sha256": sha256_file(path),
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
        "externalLinks": metadata.get("externalLinks", []),
    }


def write_catalog(files):
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    temp_path = None
    count = 0

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
            stream.write(f'  "count": {len(files)},\n')
            stream.write(
                '  "categories": '
                + json.dumps(
                    list(CATEGORIES.keys()), ensure_ascii=False
                )
                + ",\n"
            )
            stream.write('  "documents": [\n')

            for index, (folder, path) in enumerate(files):
                document = build_document(folder, path)

                if index:
                    stream.write(",\n")

                # Scrive un solo documento alla volta.
                stream.write(
                    "    "
                    + json.dumps(
                        document,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )

                count += 1

                if count % PROGRESS_EVERY == 0:
                    print(f"[PROGRESS] {count}/{len(files)}")

            stream.write("\n  ]\n")
            stream.write("}\n")
            stream.flush()
            os.fsync(stream.fileno())

        # Verifica il JSON completo prima di sostituire il catalogo.
        with temp_path.open("r", encoding="utf-8") as stream:
            json.load(stream)

        os.replace(temp_path, OUTPUT)
        temp_path = None

    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass

    return count


def main():
    print("[START] Scansione documenti...")
    files = collect_files()

    print(f"[INFO] File da indicizzare: {len(files)}")
    print("[START] Generazione catalogo a blocchi...")

    count = write_catalog(files)

    print(f"[OK] FAURE FOUNDATION: {count} file indicizzati.")
    print(f"[OK] Catalogo: {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, TypeError) as exc:
        raise SystemExit(f"[ERRORE] {exc}") from exc
