
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "documents"
OUTPUT = ROOT / "documents" / "data" / "documents.json"

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

# Esclusioni tecniche: non sono documenti da catalogare.
EXCLUDED_DIRS = {
    ".git",
    ".github",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
}

# File generati o temporanei da ignorare.
EXCLUDED_FILES = {
    ".DS_Store",
    "Thumbs.db",
}

# Metadati riconosciuti accanto a un documento:
# esempio: paper.pdf + paper.json.
METADATA_SUFFIX = ".json"


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


def load_metadata(document):
    """
    Metadati opzionali:
    accanto a documento.pdf, documento.lean, documento.md,
    ecc. può esistere documento.json.

    Il JSON associato viene utilizzato per arricchire
    il documento e non viene indicizzato autonomamente.
    """
    metadata_path = document.with_suffix(METADATA_SUFFIX)

    if not metadata_path.is_file() or metadata_path == OUTPUT:
        return {}

    try:
        metadata = json.loads(
            metadata_path.read_text(encoding="utf-8")
        )
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(
            f"Metadati non validi: {metadata_path}"
        ) from exc

    if not isinstance(metadata, dict):
        raise ValueError(
            f"I metadati devono essere un oggetto JSON: "
            f"{metadata_path}"
        )

    return metadata


def is_excluded(path):
    if path.name in EXCLUDED_FILES:
        return True

    if any(part in EXCLUDED_DIRS for part in path.parts):
        return True

    # Evita di catalogare il catalogo stesso.
    if path.resolve() == OUTPUT.resolve():
        return True

    # Evita di catalogare file JSON usati come metadati
    # di un altro documento.
    if path.suffix.lower() == ".json":
        return True

    return False


def build_document(folder, config, path):
    relative_path = path.relative_to(ROOT).as_posix()
    metadata = load_metadata(path)

    return {
        "id": f"{folder}-{path.stem}",
        "title": metadata.get(
            "title", readable_title(path.name)
        ),
        "category": folder,
        "categoryLabel": config["label"],
        "type": config["type"],
        "file": relative_path,
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
    documents = []

    for folder, config in CATEGORIES.items():
        directory = DOCS / folder
        directory.mkdir(parents=True, exist_ok=True)

        files = sorted(
            (
                path
                for path in directory.rglob("*")
                if path.is_file() and not is_excluded(path)
            ),
            key=lambda path: path.as_posix().casefold(),
        )

        for path in files:
            documents.append(
                build_document(folder, config, path)
            )

    documents.sort(
        key=lambda item: (
            item["categoryLabel"],
            item["title"].casefold(),
            item["filename"].casefold(),
        )
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    catalog = {
        "institution": "FAURE FOUNDATION",
        "catalogTitle": "Official Scientific Register",
        "generatedAt": datetime.now(
            timezone.utc
        ).isoformat(),
        "count": len(documents),
        "categories": list(CATEGORIES.keys()),
        "documents": documents,
    }

    OUTPUT.write_text(
        json.dumps(
            catalog,
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    print(
        f"FAURE FOUNDATION: "
        f"{len(documents)} file indicizzati."
    )
    print(f"Catalogo generato: {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
