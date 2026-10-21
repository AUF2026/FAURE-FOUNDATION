
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "documents"
OUTPUT = DOCS / "data" / "documents.json"

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


def readable_title(filename):
    title = Path(filename).stem
    title = re.sub(r"[_-]+", " ", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title[:1].upper() + title[1:] if title else filename


def sha256_file(path):
    digest = hashlib.sha256()

    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def relative_path(path):
    return path.relative_to(ROOT).as_posix()


def is_metadata_file(path):
    """
    Un file nome.json è un sidecar se esiste almeno
    un altro file con lo stesso nome base.
    I JSON autonomi possono essere catalogati.
    """
    if path.suffix.lower() != ".json":
        return False

    if path.resolve() == OUTPUT.resolve():
        return True

    return any(
        sibling.is_file()
        and sibling != path
        and sibling.suffix.lower() != ".json"
        for sibling in path.parent.glob(path.stem + ".*")
    )


def is_excluded(path):
    rel = path.relative_to(ROOT)

    if any(part in EXCLUDED_DIRS for part in rel.parts):
        return True

    if path.name in EXCLUDED_FILES:
        return True

    if path.resolve() == OUTPUT.resolve():
        return True

    if path.is_symlink():
        return True

    if is_metadata_file(path):
        return True

    return False


def load_metadata(document):
    metadata_path = document.with_suffix(".json")

    if metadata_path == document:
        return {}

    if not metadata_path.is_file():
        return {}

    try:
        metadata = json.loads(
            metadata_path.read_text(encoding="utf-8")
        )
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(
            f"Metadati non validi: "
            f"{relative_path(metadata_path)}"
        ) from exc

    if not isinstance(metadata, dict):
        raise ValueError(
            f"I metadati devono essere un oggetto JSON: "
            f"{relative_path(metadata_path)}"
        )

    external_links = metadata.get("externalLinks", [])

    if not isinstance(external_links, list):
        raise ValueError(
            f"externalLinks deve essere una lista: "
            f"{relative_path(metadata_path)}"
        )

    return metadata


def build_document(folder, config, path):
    rel = relative_path(path)
    metadata = load_metadata(path)

    # L'hash del percorso evita collisioni tra file omonimi.
    identifier = hashlib.sha256(
        rel.encode("utf-8")
    ).hexdigest()[:20]

    title = metadata.get("title", readable_title(path.name))

    if not isinstance(title, str) or not title.strip():
        title = readable_title(path.name)

    return {
        "id": f"{folder}-{identifier}",
        "title": title.strip(),
        "category": folder,
        "categoryLabel": config[0],
        "type": config[1],
        "file": rel,
        "filename": path.name,
        "extension": path.suffix.lower().lstrip("."),
        "sizeBytes": path.stat().st_size,
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


def main():
    if not DOCS.is_dir():
        raise SystemExit(
            f"Cartella documents non trovata: {DOCS}"
        )

    documents = []

    for folder, config in CATEGORIES.items():
        directory = DOCS / folder

        # Non creare cartelle vuote automaticamente:
        # lo script deve indicizzare ciò che esiste.
        if not directory.is_dir():
            continue

        files = sorted(
            (
                path
                for path in directory.rglob("*")
                if path.is_file() and not is_excluded(path)
            ),
            key=lambda path: relative_path(path).casefold(),
        )

        for path in files:
            documents.append(
                build_document(folder, config, path)
            )

    documents.sort(
        key=lambda item: (
            item["categoryLabel"],
            item["title"].casefold(),
            item["file"].casefold(),
        )
    )

    catalog = {
        "institution": "FAURE FOUNDATION",
        "catalogTitle": "Official Scientific Register",
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "count": len(documents),
        "categories": list(CATEGORIES.keys()),
        "documents": documents,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    content = json.dumps(
        catalog,
        ensure_ascii=False,
        indent=2,
    ) + "\n"

    OUTPUT.write_text(content, encoding="utf-8")

    print(f"FAURE FOUNDATION: {len(documents)} file indicizzati.")
    print(f"Catalogo generato: {relative_path(OUTPUT)}")


if __name__ == "__main__":
    main()
