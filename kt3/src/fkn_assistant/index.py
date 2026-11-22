"""Build and query the frozen KT3 hybrid index. Only registry documents enter the index."""

import argparse
import csv
import fcntl
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import zlib
from collections import Counter
from pathlib import Path

import numpy as np
import onnxruntime as ort
from qdrant_client import QdrantClient
from qdrant_client import models as qm
from tokenizers import Tokenizer

from fkn_assistant.config import CACHE, REPO

# The format ID describes chunking and embedding semantics. Keep it stable when
# relocating files. Bump it when the index representation or extraction changes.
INDEX_FORMAT = "695fb2c743791f3ec8399affc240a11c1509f178f4a62602dca458242b6f6b20"
REV = "1ec9243030a27d1a115d5c340572074c125b58b2"
ARTIFACTS = {
    "tokenizer.json": "62c24cdc13d4c9952d63718d6c9fa4c287974249e16b7ade6d5a85e7bbb75626",
    "model_int8.onnx": "9ddfd8b45086dabc59a7e1bb00463225dace8954962418b240840f2153bc87da",
}
URL = os.environ.get("KT3_QDRANT_URL", "http://127.0.0.1:16333")
MANIFEST = CACHE / "index.json"


def checksum(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def artifact(name):
    directory = CACHE / "e5"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    if not target.exists():
        part = target.with_suffix(".part")
        remote = ("onnx/" if name.endswith("onnx") else "") + name
        subprocess.run(
            [
                "curl",
                "-fsSL",
                "--retry",
                "3",
                "-o",
                str(part),
                f"https://huggingface.co/Xenova/multilingual-e5-base/resolve/{REV}/{remote}",
            ],
            check=True,
        )
        if checksum(part) != ARTIFACTS[name]:
            raise ValueError(f"Checksum mismatch: {name}")
        part.replace(target)
    if checksum(target) != ARTIFACTS[name]:
        raise ValueError(f"Checksum mismatch: {target}")
    return target


def tokenizer():
    tok = Tokenizer.from_file(str(artifact("tokenizer.json")))
    tok.no_padding()
    tok.no_truncation()
    return tok


class Encoder:
    def __init__(self):
        self.tok = tokenizer()
        self.tok.enable_truncation(max_length=512)
        self.tok.enable_padding(pad_id=1, pad_token="<pad>")
        options = ort.SessionOptions()
        options.intra_op_num_threads = 4
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(
            str(artifact("model_int8.onnx")),
            options,
            providers=["CPUExecutionProvider"],
        )

    def encode(self, texts):
        items = self.tok.encode_batch(texts)
        ids = np.asarray([i.ids for i in items], dtype=np.int64)
        mask = np.asarray([i.attention_mask for i in items], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": mask}
        if any(i.name == "token_type_ids" for i in self.session.get_inputs()):
            feed["token_type_ids"] = np.zeros_like(ids)
        hidden = self.session.run(None, feed)[0]
        pooled = (hidden * mask[:, :, None]).sum(1) / mask.sum(1)[:, None]
        return (pooled / np.linalg.norm(pooled, axis=1, keepdims=True)).astype(
            "float32"
        )


def terms(text):
    return re.findall(r"[а-яёa-z0-9_]+", text.lower().replace("ё", "е"))


def sparse(text, average=None):
    counts = Counter(zlib.crc32(term.encode()) for term in terms(text))
    indices = sorted(counts)
    if average is None:
        weights = [1.0] * len(indices)
    else:
        length = sum(counts.values())
        norm = 1.2 * (0.25 + 0.75 * length / average)
        weights = [2.2 * counts[i] / (counts[i] + norm) for i in indices]
    return qm.SparseVector(indices=indices, values=weights)


def sections(path, row):
    title = row["short_title"] or row["title"]
    if path.suffix == ".md":
        heading, body = title, []
        for line in path.read_text().splitlines():
            if line.startswith("#"):
                if body:
                    yield heading, "\n".join(body)
                heading, body = line.strip("# ").strip() or title, []
            elif line.strip():
                body.append(re.sub(r"\[([^]\n]+)\]\(https?://[^)\s]+\)", r"\1", line))
        if body:
            yield heading, "\n".join(body)
    elif path.suffix == ".pdf":
        import pymupdf

        with pymupdf.open(path) as pdf:
            for n, page in enumerate(pdf, 1):
                yield f"стр. {n}", page.get_text(sort=True)
    elif path.suffix == ".docx":
        from docx import Document
        from docx.table import Table

        doc = Document(path)
        heading, body, table_id = title, [], 0
        for item in doc.iter_inner_content():
            if isinstance(item, Table):
                table_id += 1
                for n, cells in enumerate(item.rows, 1):
                    yield (
                        f"{heading}, табл. {table_id}, строка {n}",
                        " | ".join(c.text for c in cells.cells),
                    )
                continue
            line = item.text.strip()
            clause = re.match(r"^(\d+(?:\.\d+)*[.)])\s+", line)
            if clause or (item.style and item.style.name.startswith("Heading")):
                if body:
                    yield heading, "\n".join(body)
                heading, body = clause[1] if clause else line[:160], []
            if line:
                body.append(line)
        if body:
            yield heading, "\n".join(body)
    elif path.suffix == ".xlsx":
        from openpyxl import load_workbook

        book = load_workbook(path, read_only=True, data_only=True)
        try:
            for sheet in book:
                for n, cells in enumerate(sheet.values, 1):
                    yield (
                        f"{sheet.title}, строка {n}",
                        " | ".join(str(v) for v in cells if v is not None),
                    )
        finally:
            book.close()


def windows(tok, text):
    text = " ".join(text.split())
    if not text:
        return
    offsets = tok.encode(text, add_special_tokens=False).offsets
    for start in range(0, len(offsets), 330):
        end = min(start + 400, len(offsets))
        yield text[offsets[start][0] : offsets[end - 1][1]]
        if end == len(offsets):
            break


def corpus_db(repo):
    corpus = repo / "tmp_dataset"
    registry = corpus / "registry.csv"
    release = hashlib.sha256(
        (checksum(registry) + INDEX_FORMAT + REV).encode()
    ).hexdigest()[:16]
    CACHE.mkdir(exist_ok=True)
    db = sqlite3.connect(CACHE / f"passages-{release}.sqlite")
    db.execute(
        "create table if not exists chunk (id integer primary key, payload text, passage text, length int, vector blob)"
    )
    db.execute(
        "create table if not exists source (doc_id text primary key, sha text, chunks int)"
    )
    tok = tokenizer()
    for row in csv.DictReader(registry.open()):
        path = corpus / row["path"]
        actual = checksum(path)
        if actual != row["sha256"]:
            raise ValueError(f"Modified corpus file {row['doc_id']}")
        if db.execute(
            "select 1 from source where doc_id=?", (row["doc_id"],)
        ).fetchone():
            continue
        count = 0
        for clause, body in sections(path, row):
            for fragment in windows(tok, body):
                count += 1
                data = {
                    k: row[k]
                    for k in (
                        "doc_id",
                        "doc_kind",
                        "title",
                        "path",
                        "source_url",
                        "is_current",
                        "academic_year",
                        "intake_year",
                        "scope",
                        "level",
                    )
                }
                data.update(
                    clause_id=clause,
                    text=fragment,
                    citation_id=f"{row['doc_id']}:{count}",
                    version=row["effective_date"]
                    or row["academic_year"]
                    or row["downloaded_at"],
                    program_ids=list(filter(None, row["program_ids"].split(";"))),
                )
                passage = f"{row['title']} — {clause}\n{fragment}"
                db.execute(
                    "insert into chunk(payload,passage,length) values(?,?,?)",
                    (
                        json.dumps(data, ensure_ascii=False),
                        passage,
                        len(terms(passage)),
                    ),
                )
        db.execute("insert into source values(?,?,?)", (row["doc_id"], actual, count))
        db.commit()
    return db, release, checksum(registry)


def build(repo):
    db, release, registry_hash = corpus_db(repo)
    name = f"kt3_b0_{release}"
    total, average = db.execute("select count(*),avg(length) from chunk").fetchone()
    print(f"Corpus ready: {total} passages", flush=True)
    encoder = Encoder()
    processed = db.execute(
        "select count(*) from chunk where vector is not null"
    ).fetchone()[0]
    pending = db.execute(
        "select id,passage from chunk where vector is null order by length,id"
    ).fetchall()
    for start in range(0, len(pending), 12):
        batch = pending[start : start + 12]
        vectors = encoder.encode(["passage: " + row[1] for row in batch])
        db.executemany(
            "update chunk set vector=? where id=?",
            [(v.tobytes(), row[0]) for row, v in zip(batch, vectors)],
        )
        db.commit()
        processed += len(batch)
        if start % 600 == 0:
            print(f"Embedded {processed}/{total}", flush=True)
    client = QdrantClient(url=URL, timeout=45)
    if not client.collection_exists(name):
        client.create_collection(
            name,
            vectors_config={
                "dense": qm.VectorParams(size=768, distance=qm.Distance.COSINE)
            },
            sparse_vectors_config={
                "bm25": qm.SparseVectorParams(modifier=qm.Modifier.IDF)
            },
        )
    cursor = db.execute("select id,payload,passage,vector from chunk order by id")
    while batch := cursor.fetchmany(96):
        client.upsert(
            name,
            points=[
                qm.PointStruct(
                    id=i,
                    payload=json.loads(p),
                    vector={
                        "dense": np.frombuffer(v, np.float32).tolist(),
                        "bm25": sparse(t, average),
                    },
                )
                for i, p, t, v in batch
            ],
            wait=True,
        )
    if client.count(name, exact=True).count != total:
        raise RuntimeError("Incomplete Qdrant index")
    manifest = dict(
        collection=name,
        registry_sha256=registry_hash,
        encoder=REV,
        encoder_files=ARTIFACTS,
        documents=db.execute("select count(*) from source").fetchone()[0],
        chunks=total,
        empty_documents=[
            r[0] for r in db.execute("select doc_id from source where chunks=0")
        ],
        average_length=average,
        corpus_commit=subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD:tmp_dataset"], text=True
        ).strip(),
        dense_top=20,
        sparse_top=20,
        fusion="Qdrant RRF",
        context_limit=5,
    )
    tmp = MANIFEST.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    tmp.replace(MANIFEST)
    print(name, total, flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=REPO)
    args = parser.parse_args()
    CACHE.mkdir(exist_ok=True)
    with (CACHE / "index.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        build(args.repo)


if __name__ == "__main__":
    main()
