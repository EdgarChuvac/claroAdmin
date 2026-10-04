"""Cliente Firestore en memoria (subconjunto de la API de google-cloud-firestore).

Se usa con ``DATA_BACKEND=memory`` para pruebas automatizadas y demostraciones
sin credenciales. Implementa únicamente las operaciones que usa
``backend.repository``; la compatibilidad con el SDK real se verifica en CI
contra el emulador oficial de Firestore (``tests/test_firestore_emulator.py``).
"""

from __future__ import annotations

import copy
import secrets
import threading
from typing import Any, Callable, Iterator

ASCENDING = "ASCENDING"
DESCENDING = "DESCENDING"


class FakeSnapshot:
    def __init__(self, reference: "FakeDocumentReference", data: dict[str, Any] | None):
        self.reference = reference
        self.id = reference.id
        self._data = copy.deepcopy(data) if data is not None else None

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> dict[str, Any] | None:
        return copy.deepcopy(self._data) if self._data is not None else None


class FakeDocumentReference:
    def __init__(self, client: "FakeFirestoreClient", collection: str, doc_id: str):
        self._client = client
        self._collection = collection
        self.id = doc_id

    @property
    def path(self) -> str:
        return f"{self._collection}/{self.id}"

    def get(self, transaction: "FakeTransaction | None" = None) -> FakeSnapshot:
        with self._client._lock:
            return FakeSnapshot(self, self._client._store(self._collection).get(self.id))

    def set(self, data: dict[str, Any], merge: bool = False) -> None:
        self._client._apply(("set", self, data, merge))

    def update(self, data: dict[str, Any]) -> None:
        self._client._apply(("update", self, data, False))

    def delete(self) -> None:
        self._client._apply(("delete", self, None, False))


class FakeQuery:
    def __init__(self, client: "FakeFirestoreClient", collection: str):
        self._client = client
        self._collection = collection
        self._filters: list[tuple[str, str, Any]] = []
        self._orders: list[tuple[str, str]] = []
        self._limit: int | None = None

    def _clone(self) -> "FakeQuery":
        query = FakeQuery(self._client, self._collection)
        query._filters = list(self._filters)
        query._orders = list(self._orders)
        query._limit = self._limit
        return query

    def where(self, field_path: str | None = None, op_string: str | None = None,
              value: Any = None, *, filter: Any = None) -> "FakeQuery":
        if filter is not None:
            field_path, op_string, value = filter.field_path, filter.op_string, filter.value
        if op_string not in {"==", "in", ">=", "<=", ">", "<", "array_contains"}:
            raise ValueError(f"Operador no soportado en el cliente en memoria: {op_string}")
        query = self._clone()
        query._filters.append((field_path, op_string, value))
        return query

    def order_by(self, field_path: str, direction: str = ASCENDING) -> "FakeQuery":
        query = self._clone()
        query._orders.append((field_path, direction))
        return query

    def limit(self, count: int) -> "FakeQuery":
        query = self._clone()
        query._limit = count
        return query

    @staticmethod
    def _match(data: dict[str, Any], field: str, op: str, value: Any) -> bool:
        if field not in data:
            return False
        current = data[field]
        if op == "==":
            return current == value
        if op == "in":
            return current in value
        if op == "array_contains":
            return isinstance(current, list) and value in current
        if current is None:
            return False
        return {
            ">=": current >= value,
            "<=": current <= value,
            ">": current > value,
            "<": current < value,
        }[op]

    def stream(self, transaction: "FakeTransaction | None" = None) -> Iterator[FakeSnapshot]:
        with self._client._lock:
            items = list(self._client._store(self._collection).items())
        results = [
            (doc_id, data)
            for doc_id, data in items
            if all(self._match(data, f, op, v) for f, op, v in self._filters)
        ]
        for field, _direction in self._orders:
            results = [item for item in results if field in item[1]]
        for field, direction in reversed(self._orders):
            results.sort(key=lambda item: item[1][field], reverse=direction == DESCENDING)
        if not self._orders:
            results.sort(key=lambda item: item[0])
        if self._limit is not None:
            results = results[: self._limit]
        for doc_id, data in results:
            yield FakeSnapshot(FakeDocumentReference(self._client, self._collection, doc_id), data)


class FakeCollectionReference(FakeQuery):
    def __init__(self, client: "FakeFirestoreClient", name: str):
        super().__init__(client, name)
        self.id = name

    def document(self, document_id: str | None = None) -> FakeDocumentReference:
        if document_id is None:
            document_id = secrets.token_hex(10)
        if not document_id or "/" in document_id:
            raise ValueError("ID de documento inválido.")
        return FakeDocumentReference(self._client, self._collection, document_id)


class FakeWriteBatch:
    MAX_OPERATIONS = 500

    def __init__(self, client: "FakeFirestoreClient"):
        self._client = client
        self._ops: list[tuple[str, FakeDocumentReference, Any, bool]] = []

    def _add(self, op: tuple[str, FakeDocumentReference, Any, bool]) -> None:
        if len(self._ops) >= self.MAX_OPERATIONS:
            raise ValueError("Un lote de Firestore admite como máximo 500 operaciones.")
        self._ops.append(op)

    def set(self, reference: FakeDocumentReference, data: dict[str, Any], merge: bool = False) -> None:
        self._add(("set", reference, data, merge))

    def update(self, reference: FakeDocumentReference, data: dict[str, Any]) -> None:
        self._add(("update", reference, data, False))

    def delete(self, reference: FakeDocumentReference) -> None:
        self._add(("delete", reference, None, False))

    def commit(self) -> None:
        self._client._apply(*self._ops)
        self._ops = []


class FakeTransaction(FakeWriteBatch):
    pass


def transactional(func: Callable[..., Any]) -> Callable[..., Any]:
    """Equivalente en memoria de ``google.cloud.firestore.transactional``."""

    def wrapper(transaction: FakeTransaction, *args: Any, **kwargs: Any) -> Any:
        client = transaction._client
        with client._lock:
            result = func(transaction, *args, **kwargs)
            transaction.commit()
            return result

    return wrapper


class FakeFirestoreClient:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._data: dict[str, dict[str, dict[str, Any]]] = {}

    def _store(self, collection: str) -> dict[str, dict[str, Any]]:
        return self._data.setdefault(collection, {})

    def _apply(self, *ops: tuple[str, FakeDocumentReference, Any, bool]) -> None:
        with self._lock:
            # Validar primero para que el lote sea atómico.
            for kind, ref, _data, _merge in ops:
                if kind == "update" and ref.id not in self._store(ref._collection):
                    raise KeyError(f"No existe el documento {ref.path}")
            for kind, ref, data, merge in ops:
                store = self._store(ref._collection)
                if kind == "delete":
                    store.pop(ref.id, None)
                elif kind == "set" and not merge:
                    store[ref.id] = copy.deepcopy(data)
                else:
                    store.setdefault(ref.id, {}).update(copy.deepcopy(data))

    def collection(self, name: str) -> FakeCollectionReference:
        return FakeCollectionReference(self, name)

    def batch(self) -> FakeWriteBatch:
        return FakeWriteBatch(self)

    def transaction(self, **_options: Any) -> FakeTransaction:
        return FakeTransaction(self)
