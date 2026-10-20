
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "documents"
OUTPUT = ROOT / "data" / "documents.json"

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
        "type": "theory",
    },
    "proofs": {
        "label": "DIMOSTRAZIONI",
        "type": "proof",
    },
    "data": {
        "label": "DATI E VERIFICHE",
        "type": "data",
    },
    "protocols": {
        "label": "PROTOCOLLI",
        "type": "protocol",
    },
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

def load_metadata(pdf):
    """
    Metadata opzionali:
    accanto a documento.pdf può esistere documento.json.
    I metadati consentono di collegare verifiche,
    identificativi e rapporti al PDF esatto.
    """
    metadata_path = pdf.with_suffix(".json")

    if not metadata_path.is_file():
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

def build_document(folder, config, pdf):
    relative_path = pdf.relative_to(ROOT).as_posix()
    metadata = load_metadata(pdf)

    return {
        "id": f"{folder}-{pdf.stem}",
        "title": metadata.get(
            "title", readable_title(pdf.name)
        ),
        "category": folder,
        "categoryLabel": config["label"],
        "type": config["type"],
        "file": relative_path,
        "filename": pdf.name,
        "sizeBytes": pdf.stat().st_size,
        "sha256": sha256_file(pdf),
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

        for pdf in sorted(
            directory.rglob("*.pdf"),
            key=lambda path: path.as_posix().casefold(),
        ):
            documents.append(
                build_document(folder, config, pdf)
            )

    documents.sort(
        key=lambda item: (
            item["categoryLabel"],
            item["title"].casefold(),
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
        f"{len(documents)} PDF indicizzati."
    )
    print(f"Catalogo generato: {OUTPUT.relative_to(ROOT)}")

if __name__ == "__main__":
    main()
